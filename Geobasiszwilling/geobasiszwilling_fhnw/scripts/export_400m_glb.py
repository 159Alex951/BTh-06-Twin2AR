import argparse
import json
import math
import os
import subprocess
from pathlib import Path
import trimesh
import numpy as np

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

    print("Fetching grids...")
    grid_query = """
    SELECT 
        grid_id,
        ST_X(ST_Centroid(geom)) as cx,
        ST_Y(ST_Centroid(geom)) as cy
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

    try:
        from pyproj import Transformer
        lv95_to_wgs84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
        wgs84_to_ecef = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)
    except ImportError:
        print("Please install 'pyproj' in your python environment (pip install pyproj).")
        return

    def to_enu(lon, lat, alt, ax, ay, az, sin_lon, cos_lon, sin_lat, cos_lat):
        vx, vy, vz = wgs84_to_ecef.transform(lon, lat, alt)
        dx, dy, dz = vx - ax, vy - ay, vz - az
        e = -sin_lon * dx + cos_lon * dy
        n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        u =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return e, n, u

    tileset_children = []

    center_query = """
    SELECT ST_X(ST_Centroid(ST_Extent(geom))), ST_Y(ST_Centroid(ST_Extent(geom))) 
    FROM citydb.building_grid_400m;
    """
    center_res = run_query(center_query, args)
    global_cx, global_cy = map(float, center_res.split('|'))
    anchor_lon, anchor_lat = lv95_to_wgs84.transform(global_cx, global_cy)
    anchor_alt = 0.0
    
    anchor_dict = {
        "longitude": anchor_lon,
        "latitude": anchor_lat,
        "altitude": anchor_alt
    }
    with open(out_dir / "anchor.json", "w") as f:
        json.dump(anchor_dict, f, indent=2)
    print(f"Global anchor created at lon {anchor_lon:.5f}, lat {anchor_lat:.5f}")

    sin_lon = math.sin(math.radians(anchor_lon))
    cos_lon = math.cos(math.radians(anchor_lon))
    sin_lat = math.sin(math.radians(anchor_lat))
    cos_lat = math.cos(math.radians(anchor_lat))
    ax, ay, az = wgs84_to_ecef.transform(anchor_lon, anchor_lat, anchor_alt)

    for g in grids:
        gid = g["grid_id"]
        name_x = int(round(g["cx"]))
        name_y = int(round(g["cy"]))
        glb_name = f"{name_x}_{name_y}.glb"
        glb_path = out_dir / glb_name

        # Calculate exact center anchor for this specific tile
        tile_lon, tile_lat = lv95_to_wgs84.transform(g["cx"], g["cy"])
        tax, tay, taz = wgs84_to_ecef.transform(tile_lon, tile_lat, 0.0)
        tsin_lon, tcos_lon = math.sin(math.radians(tile_lon)), math.cos(math.radians(tile_lon))
        tsin_lat, tcos_lat = math.sin(math.radians(tile_lat)), math.cos(math.radians(tile_lat))

        buildings_query = f"""
        SELECT 
            citydb_objectid,
            ST_AsGeoJSON(ST_Transform(ST_Force3D((ST_Dump(citydb_geometry)).geom), 4326)) as geom
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
        # First pass to find the lowest altitude (Z) of the tile
        min_alt = float('inf')
        for line in lines:
            parts = line.split('|', 1)
            if len(parts) < 2:
                continue
            objid = parts[0]
            try:
                geom = json.loads(parts[1])
            except json.JSONDecodeError:
                continue
            
            # Simple recursive search for lowest Z coordinate to anchor the tile's origin
            coords_str = str(geom.get("coordinates", []))
            for p in geom.get("coordinates", []):
                pass # it's complex to parse recursively like this, just parse during main loop
            if objid not in buildings:
                buildings[objid] = []
            buildings[objid].append(geom)

        scene = trimesh.Scene()
        has_geometry = False
        
        # Determine exact altitude offset to push building bases to exactly 0 in the GLB origin
        all_alts = []
        def extract_alts(arr):
            for item in arr:
                if isinstance(item, list):
                    if len(item) >= 3 and isinstance(item[0], (int, float)):
                        all_alts.append(item[2])
                    else:
                        extract_alts(item)

        for objid, faces in buildings.items():
            for geom in faces:
                gtype = geom.get("type", "")
                coords = geom.get("coordinates", [])
                
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
                    extract_alts(poly)

        tile_alt = min(all_alts) if all_alts else 0.0
        
        # Now recalculate ECEF parameters using the correct terrain altitude anchor for this specific tile!
        tax, tay, taz = wgs84_to_ecef.transform(tile_lon, tile_lat, tile_alt)

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
                            lon, lat = p[0], p[1]
                            alt = p[2] if len(p) > 2 else 0.0
                            e, n, u = to_enu(lon, lat, alt, tax, tay, taz, tsin_lon, tcos_lon, tsin_lat, tcos_lat)
                            # Convert ENU (Z-up) to glTF natively expected Y-up coordinate system
                            # X = East, Y = Up, Z = South (-North)
                            verts.append((e, u, -n))
                        
                        # Add vertices to the building mesh
                        b_verts.extend(verts)
                        
                        n_pts = len(pts)
                        # Fan triangulation
                        for i in range(1, n_pts - 1):
                            b_faces.append([v_offset, v_offset + i, v_offset + i + 1])
                        
                        v_offset += n_pts
            
            if len(b_faces) > 0:
                # Due to coordinate differences between GLB and our assumptions,
                # we will just pack the raw ENU coordinates. Cesium handles it with the anchor transform.
                mesh = trimesh.Trimesh(vertices=b_verts, faces=b_faces, process=False)
                # Rotate X/Z or keep it raw ENU? Since GLB is standard, let's let trimesh export normally. 
                # Cesium will apply the Cartesian reference matrix.
                scene.add_geometry(mesh, node_name=f"building_{objid}", geom_name=f"geom_{objid}")
                has_geometry = True

        if has_geometry:
            # Export to GLB
            scene.export(str(glb_path), file_type='glb')
            
            # Add to tileset.json representing the GLB
            bbox_query = f"""
            SELECT ST_XMin(ST_Transform(geom, 4326)), ST_YMin(ST_Transform(geom, 4326)), 
                   ST_XMax(ST_Transform(geom, 4326)), ST_YMax(ST_Transform(geom, 4326))
            FROM citydb.building_grid_400m WHERE grid_id = {gid}
            """
            bbox_res = run_query(bbox_query, args)
            if bbox_res:
                xmin, ymin, xmax, ymax = map(float, bbox_res.split('|'))
                
                # Transform matrix to put the Y-up glTF back onto the Z-up ECEF globe exactly at the tile origin!
                olam = math.radians(tile_lon)
                ophi = math.radians(tile_lat)
                sl = math.sin(olam)
                cl = math.cos(olam)
                sp = math.sin(ophi)
                cp = math.cos(ophi)
                
                # ENU vector basis inside ECEF 
                # East
                e_x = -sl
                e_y = cl
                e_z = 0
                # North
                n_x = -sp * cl
                n_y = -sp * sl
                n_z = cp
                # Up
                u_x = cp * cl
                u_y = cp * sl
                u_z = sp
                
                # glTF is Y-up where X=East, Y=Up, Z=-North (South)
                # Cesium automatically maps glTF Y-up to local Z-up BEFORE applying transform.
                # So the local space before transform IS ENU (X=East, Y=North, Z=Up).
                # Therefore, we just provide the standard ENU to ECEF transform:
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
                        "center": [name_x, name_y],
                        "anchor": [tile_lon, tile_lat, tile_alt]
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