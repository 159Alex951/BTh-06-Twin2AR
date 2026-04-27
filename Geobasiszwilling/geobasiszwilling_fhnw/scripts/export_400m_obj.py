import argparse
import json
import math
import os
import subprocess
from pathlib import Path

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

def ecef_to_wgs84(x, y, z):
    # Simplistic ECEF to WGS84 just to get approximate anchor lat/lon if needed, 
    # but we can rely on pyproj if it was installed.
    # Since we're parsing straight from EPSG:4326 via ST_Transform in the query, we avoid pyproj for DB output!
    pass

def main():
    args = setup_argparse()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching grids...")
    # Get all grid bounding boxes, their center LV95 coordinates
    # We use LV95 (EPSG:2056) center coordinates to name the files!
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

    # We need a WGS84 -> ECEF transform to write correct OBJ coordinates.
    # Since ar_env has `pyproj`, we import it here!
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

    # Build a tileset.json representing the overall collection
    tileset_children = []

    # First, get globally approximate bounding box to establish the global anchor (if you want *one* anchor for all tiles)
    # The user asked for "ideally one anchor ( the tileset.json for all the tiles)"
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
        # Format the name based on center coordinate in LV95 (rounded)
        # e.g., 2615000_1265000.obj
        name_x = int(round(g["cx"]))
        name_y = int(round(g["cy"]))
        obj_name = f"{name_x}_{name_y}.obj"
        obj_path = out_dir / obj_name

        # Get buildings for this tile with 3D coordinates! 
        # Wait, v_buildings_400m_tiles has citydb_geometry which is a 3D PolyhedralSurface in LV95 (EPSG:2056).
        # We should let PostgreSQL extract the triangles/polygons and transform them to WGS84 for us, 
        # or we just fetch the vertices in LV95, convert to WGS84, then to ENU.
        # ST_Dump parses multipolygons
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

        v_offset = 0
        with open(obj_path, "w") as f:
            f.write(f"# Grid Center: {name_x}, {name_y}\n")
            f.write(f"# Global Anchor: {anchor_lon}, {anchor_lat}, {anchor_alt}\n")
            
            for b_idx, (objid, faces) in enumerate(buildings.items()):
                f.write(f"\ng building_{objid}\n")
                
                for geom in faces:
                    coords = geom.get("coordinates", [])
                    gtype = geom.get("type", "")

                    polygons = []
                    if gtype == "Polygon":
                        polygons = [coords]
                    elif gtype == "MultiPolygon":
                        polygons = coords
                    elif gtype == "GeometryCollection":
                        # Some 3D citydb geoms come as geometry collections of polygons
                        for subgeom in geom.get("geometries", []):
                            if subgeom["type"] == "Polygon":
                                polygons.append(subgeom["coordinates"])
                            elif subgeom["type"] == "MultiPolygon":
                                polygons.extend(subgeom["coordinates"])
                    
                    for poly in polygons:
                        # A polygon is a list of rings. First ring is exterior, rest are interior.
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
                                verts.append(to_enu(lon, lat, alt, ax, ay, az, sin_lon, cos_lon, sin_lat, cos_lat))
                            
                            for vx, vy, vz in verts:
                                f.write(f"v {vx:.4f} {vy:.4f} {vz:.4f}\n")
                            
                            n_pts = len(pts)
                            for i in range(1, n_pts - 1):
                                f.write(f"f {v_offset + 1} {v_offset + i + 1} {v_offset + i + 2}\n")
                            
                            v_offset += n_pts

        # Add to tileset.json
        # Convert bounding box to region for tileset
        bbox_query = f"""
        SELECT ST_XMin(ST_Transform(geom, 4326)), ST_YMin(ST_Transform(geom, 4326)), 
               ST_XMax(ST_Transform(geom, 4326)), ST_YMax(ST_Transform(geom, 4326))
        FROM citydb.building_grid_400m WHERE grid_id = {gid}
        """
        bbox_res = run_query(bbox_query, args)
        if bbox_res:
            xmin, ymin, xmax, ymax = map(float, bbox_res.split('|'))
            tileset_children.append({
                "boundingVolume": {
                    "region": [
                        math.radians(xmin), math.radians(ymin), 
                        math.radians(xmax), math.radians(ymax), 
                        0, 500
                    ]
                },
                "geometricError": 0.0,
                "content": {
                    "uri": obj_name
                },
                "extras": {
                    "name": obj_name,
                    "center": [name_x, name_y]
                }
            })
            
    # Write tileset.json
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
