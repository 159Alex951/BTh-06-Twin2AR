import argparse
import json
import math
import os
import subprocess
from pathlib import Path
import trimesh
from pyproj import Transformer

def setup_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-host", default="localhost", help="DB Host")
    parser.add_argument("--db-port", default="5432", help="DB Port")
    parser.add_argument("--db-user", default="postgres", help="DB User")
    parser.add_argument("--db-pass", default="admin", help="DB Password")
    parser.add_argument("--db-name", default="postgres", help="DB Name")
    parser.add_argument("--container", default="geobasiszwilling-citydb_pg-1", help="Docker container name")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    return parser.parse_args()

def run_query(query, args):
    cmd = [
        "docker", "exec", args.container,
        "psql", "-U", args.db_user, "-d", args.db_name, "-t", "-A", "-c", query
    ]
    try:
        res = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, encoding='utf-8')
        return res.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error querying Postgres:\n{e.output}")
        return None

def main():
    args = setup_argparse()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching grids (WGS 84)...")
    grid_query = """
    SELECT 
        grid_id,
        ST_X(ST_Centroid(ST_Transform(geom, 4326))) as cx,
        ST_Y(ST_Centroid(ST_Transform(geom, 4326))) as cy
    FROM citydb.building_grid_400m
    ORDER BY grid_id;
    """
    grid_res = run_query(grid_query, args)
    if not grid_res:
        print("No grids found.")
        return

    grids = []
    for line in grid_res.split('\n'):
        if not line: continue
        parts = line.split('|')
        grids.append({
            "grid_id": int(parts[0]),
            "cx": float(parts[1]),
            "cy": float(parts[2])
        })

    print(f"Found {len(grids)} grids.")

    # Get Global center in WGS 84
    center_query = """
    SELECT ST_X(ST_Centroid(ST_Extent(ST_Transform(geom, 4326)))), ST_Y(ST_Centroid(ST_Extent(ST_Transform(geom, 4326))))
    FROM citydb.building_grid_400m;
    """
    center_res = run_query(center_query, args)
    global_cx, global_cy = map(float, center_res.split('|'))
    
    anchor_dict = {
        "longitude": global_cx,
        "latitude": global_cy,
        "altitude": 0.0
    }
    with open(out_dir / "anchor.json", "w") as f:
        json.dump(anchor_dict, f, indent=2)
    print(f"Global anchor created at lon {global_cx:.5f}, lat {global_cy:.5f}")

    wgs84_to_ecef = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)

    def to_enu(vx, vy, vz, ax, ay, az, sin_lon, cos_lon, sin_lat, cos_lat):
        dx, dy, dz = vx - ax, vy - ay, vz - az
        e = -sin_lon * dx + cos_lon * dy
        n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        u =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return e, n, u

    tileset_children = []

    for g in grids:
        gid = g["grid_id"]
        # Use simple coordinate based naming
        name_x = int(g["cx"] * 1000)
        name_y = int(g["cy"] * 1000)
        glb_name = f"wgs84_{gid}.glb"
        glb_path = out_dir / glb_name

        print(f"Exporting grid {gid} to {glb_name}...")
        
        # Determine strict ENU center in EPSG:4978 (ECEF)
        tile_lon, tile_lat = g["cx"], g["cy"]
        tile_alt = 0.0 # anchor at 0 height to avoid floating
        tax, tay, taz = wgs84_to_ecef.transform(tile_lon, tile_lat, tile_alt)
        tsin_lon, tcos_lon = math.sin(math.radians(tile_lon)), math.cos(math.radians(tile_lon))
        tsin_lat, tcos_lat = math.sin(math.radians(tile_lat)), math.cos(math.radians(tile_lat))

        # Request transformed ECEF (EPSG:4978) geometry directly from PostGIS in meters!
        buildings_query = f"""
        SELECT 
            citydb_objectid,
            ST_AsGeoJSON(ST_Force3D((ST_Dump(ST_Transform(citydb_geometry, 4978))).geom)) as geom
        FROM citydb.v_buildings_400m_tiles
        WHERE grid_id = {gid} AND citydb_geometry IS NOT NULL
        """
        feats_raw = run_query(buildings_query, args)
        if not feats_raw:
            continue

        lines = [line for line in feats_raw.split('\n') if line.strip()]
        if not lines:
            continue

        buildings = {}
        for line in lines:
            parts = line.split('|', 1)
            if len(parts) < 2:
                continue
            objid = parts[0]
            try:
                geom = json.loads(parts[1])
            except json.JSONDecodeError:
                continue
            
            if objid not in buildings:
                buildings[objid] = []
            buildings[objid].append(geom)

        scene = trimesh.Scene()
        has_geometry = False
        
        for objid, faces in buildings.items():
            b_verts = []
            b_faces = []
            v_offset = 0
            
            for geom in faces:
                coords = geom.get("coordinates", [])
                gtype = geom.get("type", "")

                polygons = []
                if gtype == "Polygon":
                    polygons = [coords]
                elif gtype == "MultiPolygon":
                    polygons = coords
                elif gtype == "GeometryCollection":
                    for subgeom in geom.get("geometries", []):
                        if subgeom["type"] == "Polygon":
                            polygons.append(subgeom["coordinates"])
                        elif subgeom["type"] == "MultiPolygon":
                            polygons.extend(subgeom["coordinates"])
                
                for poly in polygons:
                    for ring in poly:
                        pts = ring
                        if pts[0] == pts[-1]:
                            pts = pts[:-1]
                        
                        if len(pts) < 3:
                            continue
                        
                        verts = []
                        for p in pts:
                            # p is [X, Y, Z] directly in ECEF (EPSG:4978) in meters now!
                            vx, vy = p[0], p[1]
                            vz = p[2] if len(p) > 2 else 0.0
                            
                            # Standardize to local metric coordinate space (East, North, Up) relative to tile center
                            e, n, u = to_enu(vx, vy, vz, tax, tay, taz, tsin_lon, tcos_lon, tsin_lat, tcos_lat)
                            
                            # Y-up glTF coordinate system
                            # X = East (meters), Y = Up (meters), Z = -North (meters)
                            verts.append((e, u, -n))
                        
                        b_verts.extend(verts)
                        n_pts = len(pts)
                        # Fan triangulation
                        for i in range(1, n_pts - 1):
                            b_faces.append([v_offset, v_offset + i, v_offset + i + 1])
                        
                        v_offset += n_pts
            
            if len(b_faces) > 0:
                mesh = trimesh.Trimesh(vertices=b_verts, faces=b_faces, process=False)
                scene.add_geometry(mesh, node_name=f"building_{objid}", geom_name=f"geom_{objid}")
                has_geometry = True

        if has_geometry:
            scene.export(str(glb_path), file_type='glb')
            
            bbox_query = f"""
            SELECT ST_XMin(ST_Transform(geom, 4326)), ST_YMin(ST_Transform(geom, 4326)), 
                   ST_XMax(ST_Transform(geom, 4326)), ST_YMax(ST_Transform(geom, 4326))
            FROM citydb.building_grid_400m WHERE grid_id = {gid}
            """
            bbox_res = run_query(bbox_query, args)
            if bbox_res:
                xmin, ymin, xmax, ymax = map(float, bbox_res.split('|'))
                
                # Transform matrix to put the Y-up glTF back onto the Z-up ECEF globe exactly at the tile origin!
                sl = math.sin(math.radians(tile_lon))
                cl = math.cos(math.radians(tile_lon))
                sp = math.sin(math.radians(tile_lat))
                cp = math.cos(math.radians(tile_lat))
                
                # ENU vector basis inside ECEF 
                e_x, e_y, e_z = -sl, cl, 0
                n_x, n_y, n_z = -sp * cl, -sp * sl, cp
                u_x, u_y, u_z = cp * cl, cp * sl, sp
                
                transform = [
                    e_x, e_y, e_z, 0,
                    n_x, n_y, n_z, 0,
                    u_x, u_y, u_z, 0,
                    tax, tay, taz, 1
                ]
                
                tileset_children.append({
                    "boundingVolume": {
                        "region": [
                            math.radians(xmin), math.radians(ymin), 
                            math.radians(xmax), math.radians(ymax), 
                            0, 500
                        ]
                    },
                    "geometricError": 0.0,
                    "transform": transform,
                    "content": {
                        "uri": glb_name
                    },
                    "extras": {
                        "name": glb_name,
                        "anchor_wgs84": [g["cx"], g["cy"]]
                    }
                })
            
    tileset = {
        "asset": {"version": "1.0"},
        "geometricError": 500.0,
        "root": {
            "boundingVolume": {
                "region": [
                    math.radians(5.96), math.radians(45.82),
                    math.radians(10.49), math.radians(47.81),
                    0, 5000
                ]
            },
            "geometricError": 500.0,
            "refine": "ADD",
            "children": tileset_children
        }
    }
    with open(out_dir / "tileset.json", "w") as f:
        json.dump(tileset, f, indent=2)

    print(f"Exported {len(grids)} tiles to {out_dir}")

if __name__ == "__main__":
    main()