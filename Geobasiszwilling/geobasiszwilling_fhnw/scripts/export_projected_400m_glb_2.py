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

        # Query the new projected 2D DB, passing bounding grids using ST_Intersects
        # Bring z_base and computed_height separately
        buildings_query = f"""
        SELECT 
            fid,
            z_base,
            computed_height,
            ST_AsGeoJSON(ST_Transform(p.geom, 4326)) as geometry
        FROM citydb.projected_buildings_2d p
        JOIN citydb.building_grid_400m g ON ST_Intersects(p.geom, g.geom)
        WHERE g.grid_id = {gid}
        """
        feats_raw = run_query(buildings_query, args)
        if not feats_raw:
            continue

        lines = [line for line in feats_raw.split('\n') if line.strip()]
        if not lines:
            continue

        buildings = {}
        # First pass to find the lowest altitude (Z) of the tile across all footprints
        min_alt = float('inf')
        for line in lines:
            parts = line.split('|', 3)
            if len(parts) < 4:
                continue
            objid = parts[0]
            try:
                z_base = float(parts[1])
                computed_height = float(parts[2])
                geom = json.loads(parts[3])
                
                # Check for minimum altitude using the fetched base altitudes
                if z_base < min_alt:
                    min_alt = z_base
            except (ValueError, json.JSONDecodeError):
                continue
            
            if objid not in buildings:
                buildings[objid] = []
            buildings[objid].append({"z_base": z_base, "computed_height": computed_height, "geom": geom})

        scene = trimesh.Scene()
        has_geometry = False
        
        tile_alt = min_alt if min_alt != float('inf') else 0.0
        
        # Recalculate ECEF parameters using the correct terrain altitude anchor for this specific tile!
        tax, tay, taz = wgs84_to_ecef.transform(tile_lon, tile_lat, tile_alt)

        for objid, data_arr in buildings.items():
            for data in data_arr:
                geom = data["geom"]
                z_base = data["z_base"]
                computed_height = data["computed_height"]
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
                
                # Trimesh expects 3D volume, so we use Polygon extrude
                for poly in polygons:
                    # usually poly[0] is exterior, rest are holes
                    exterior_ring = poly[0]
                    # close the ring logically if not 
                    if exterior_ring[0] != exterior_ring[-1]:
                        exterior_ring.append(exterior_ring[0])
                        
                    # Create 2D shapely-like structure for trimesh extrusion
                    try:
                        pts = [(p[0], p[1]) for p in exterior_ring]
                        # We use trimesh creation of polygons
                        from shapely.geometry import Polygon
                        shape_poly = Polygon(pts)
                        # Extrude upwards by computed_height based on WGS84 degree length?
                        # Trimesh extrusion requires Cartesian.
                        # It is much safer to convert footprint directly to ENU Cartesian, then extrude!
                        
                        cartesian_pts = []
                        for p in exterior_ring:
                            e, n, u = to_enu(p[0], p[1], z_base, tax, tay, taz, tsin_lon, tcos_lon, tsin_lat, tcos_lat)
                            # Preserve true ENU locally for Trimesh creation
                            cartesian_pts.append([e, n]) 
                            
                        cartesian_poly = Polygon(cartesian_pts)
                        if not cartesian_poly.is_valid:
                            cartesian_poly = cartesian_poly.buffer(0)
                        
                        # Extrude by computed_height (Trimesh uses Z for height internally)
                        mesh = trimesh.creation.extrude_polygon(cartesian_poly, height=computed_height)
                        
                        # Rotate the mesh from Trimesh (X=E, Y=N, Z=Up) to glTF (X=East, Y=Up, Z=South(-North))
                        # Trimesh X -> glTF X (East -> East)
                        # Trimesh Z -> glTF Y (Up -> Up)
                        # Trimesh Y -> glTF -Z (North -> -Z. In glTF +Z is South, so -Z is North)
                        transform_to_gltf = np.array([
                            [1, 0, 0, 0],
                            [0, 0, 1, 0],  # Trimesh Z goes to glTF Y
                            [0, -1, 0, 0], # Trimesh Y goes to glTF -Z
                            [0, 0, 0, 1]
                        ])
                        mesh.apply_transform(transform_to_gltf)
                        
                        # Shift up by the tile's diff from z_base
                        # the polygon Z is local U
                        # u = local Up, which was 0 from our local anchor math
                        dummy_e, dummy_n, local_base_u = to_enu(exterior_ring[0][0], exterior_ring[0][1], z_base, tax, tay, taz, tsin_lon, tcos_lon, tsin_lat, tcos_lat)
                        
                        # Shift the entire extruded mesh up by the local ground height mapping to Y
                        mesh.apply_translation([0, local_base_u, 0])

                        scene.add_geometry(mesh, node_name=f"building_{objid}_{id(mesh)}", geom_name=f"geom_{objid}_{id(mesh)}")
                        has_geometry = True
                    except Exception as ex:
                        print(f"Failed to extrude building {objid}: {ex}")

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