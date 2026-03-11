"""
Standalone script: fetch 2D projected building footprints from WFS (ms:LCSFPROJ),
extrude them to 3D with a fixed height, and export as OBJ + anchor.json.

Usage:
    python projected_buildings_to_obj.py \
        --bbox 7.62,47.52,7.64,47.54 \
        --height 10.0 \
        --out projected_buildings.obj
"""

import argparse
import json
import math
import requests
from pyproj import Transformer

WFS_URL = "https://geodienste.ch/db/av_0/deu"
LAYER = "ms:LCSFPROJ"

# LV95 -> WGS84
_lv95_to_wgs84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
# WGS84 -> ECEF
_wgs84_to_ecef = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)


def fetch_lcsfproj(bbox_wgs84: tuple, max_features=500):
    """Fetch LCSFPROJ features as GeoJSON for a WGS84 bounding box."""
    west, south, east, north = bbox_wgs84
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": LAYER,
        "OUTPUTFORMAT": "application/json; subtype=geojson",
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
        "COUNT": max_features,
    }
    resp = requests.get(WFS_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def polygon_to_obj(ring_wgs84: list, height_m: float):
    """
    Extrude a 2D polygon ring (WGS84 lon/lat) into a 3D OBJ mesh.
    Returns (vertices, faces) where vertices are ENU meter-offsets from centroid.
    """
    # Compute centroid for anchor
    lons = [p[0] for p in ring_wgs84]
    lats = [p[1] for p in ring_wgs84]
    anchor_lon = sum(lons) / len(lons)
    anchor_lat = sum(lats) / len(lats)
    anchor_alt = 0.0  # ground level — adjust later with terrain

    # ENU rotation matrix at anchor
    sin_lon = math.sin(math.radians(anchor_lon))
    cos_lon = math.cos(math.radians(anchor_lon))
    sin_lat = math.sin(math.radians(anchor_lat))
    cos_lat = math.cos(math.radians(anchor_lat))

    ax, ay, az = _wgs84_to_ecef.transform(anchor_lon, anchor_lat, anchor_alt)

    def to_enu(lon, lat, alt):
        vx, vy, vz = _wgs84_to_ecef.transform(lon, lat, alt)
        dx, dy, dz = vx - ax, vy - ay, vz - az
        e = -sin_lon * dx + cos_lon * dy
        n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        u =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return e, n, u

    # Build floor + roof rings (skip closing duplicate point)
    pts = ring_wgs84[:-1] if ring_wgs84[0] == ring_wgs84[-1] else ring_wgs84
    n_pts = len(pts)

    floor_verts = [to_enu(p[0], p[1], anchor_alt) for p in pts]
    roof_verts  = [to_enu(p[0], p[1], anchor_alt + height_m) for p in pts]

    vertices = floor_verts + roof_verts  # floor = 0..n-1, roof = n..2n-1

    faces = []
    # Walls
    for i in range(n_pts):
        j = (i + 1) % n_pts
        # Two triangles per wall quad (1-based OBJ indices)
        faces.append((i+1,        j+1,        n_pts+j+1))
        faces.append((i+1,        n_pts+j+1,  n_pts+i+1))
    # Roof (simple fan triangulation from first point)
    for i in range(1, n_pts - 1):
        faces.append((n_pts+1, n_pts+i+1, n_pts+i+2))
    # Floor (reversed winding)
    for i in range(1, n_pts - 1):
        faces.append((1, i+2, i+1))

    return vertices, faces, (anchor_lon, anchor_lat, anchor_alt)


def features_to_obj(geojson: dict, height_m: float, out_path: str):
    features = geojson.get("features", [])
    if not features:
        print("No features found in response.")
        return

    # --- STEP 1: compute global anchor from all feature centroids ---
    all_lons, all_lats = [], []
    for feat in features:
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [])
        gtype = geom.get("type")
        rings = []
        if gtype == "Polygon":
            rings = [coords[0]]
        elif gtype == "MultiPolygon":
            rings = [poly[0] for poly in coords]
        for ring in rings:
            pts = ring[:-1] if ring[0] == ring[-1] else ring
            all_lons.extend(p[0] for p in pts)
            all_lats.extend(p[1] for p in pts)

    if not all_lons:
        print("No geometry found.")
        return

    anchor_lon = sum(all_lons) / len(all_lons)
    anchor_lat = sum(all_lats) / len(all_lats)
    anchor_alt = 0.0

    # Write anchor JSON
    anchor_path = out_path.replace(".obj", ".anchor.json")
    with open(anchor_path, "w") as f:
        json.dump({"longitude": anchor_lon, "latitude": anchor_lat, "altitude": anchor_alt}, f)
    print(f"Anchor: {anchor_lon:.6f}, {anchor_lat:.6f}")

    # ENU rotation matrix at global anchor
    sin_lon = math.sin(math.radians(anchor_lon))
    cos_lon = math.cos(math.radians(anchor_lon))
    sin_lat = math.sin(math.radians(anchor_lat))
    cos_lat = math.cos(math.radians(anchor_lat))
    ax, ay, az = _wgs84_to_ecef.transform(anchor_lon, anchor_lat, anchor_alt)

    def to_enu(lon, lat, alt):
        vx, vy, vz = _wgs84_to_ecef.transform(lon, lat, alt)
        dx, dy, dz = vx - ax, vy - ay, vz - az
        e = -sin_lon * dx + cos_lon * dy
        n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        u =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return e, n, u

    # --- STEP 2: write all buildings relative to global anchor ---
    v_offset = 0
    with open(out_path, "w") as f:
        f.write("# Projected buildings extruded from WFS ms:LCSFPROJ\n")

        for feat_idx, feat in enumerate(features):
            geom = feat.get("geometry", {})
            gtype = geom.get("type")
            coords = geom.get("coordinates", [])

            rings = []
            if gtype == "Polygon":
                rings = [coords[0]]
            elif gtype == "MultiPolygon":
                rings = [poly[0] for poly in coords]
            else:
                continue

            for ring in rings:
                pts = ring[:-1] if ring[0] == ring[-1] else ring
                if len(pts) < 3:
                    continue

                floor_verts = [to_enu(p[0], p[1], anchor_alt) for p in pts]
                roof_verts  = [to_enu(p[0], p[1], anchor_alt + height_m) for p in pts]
                verts = floor_verts + roof_verts
                n_pts = len(pts)

                faces = []
                for i in range(n_pts):
                    j = (i + 1) % n_pts
                    faces.append((i+1, j+1, n_pts+j+1))
                    faces.append((i+1, n_pts+j+1, n_pts+i+1))
                for i in range(1, n_pts - 1):
                    faces.append((n_pts+1, n_pts+i+1, n_pts+i+2))
                for i in range(1, n_pts - 1):
                    faces.append((1, i+2, i+1))

                f.write(f"\ng projected_building_{feat_idx}\n")
                for vx, vy, vz in verts:
                    f.write(f"v {vx:.4f} {vy:.4f} {vz:.4f}\n")
                for face in faces:
                    adjusted = tuple(idx + v_offset for idx in face)
                    f.write(f"f {adjusted[0]} {adjusted[1]} {adjusted[2]}\n")
                v_offset += len(verts)

    print(f"Exported {len(features)} features to {out_path}")



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", required=True, help="west,south,east,north in WGS84")
    parser.add_argument("--height", type=float, default=10.0, help="Extrusion height in meters")
    parser.add_argument("--out", default="projected_buildings.obj")
    args = parser.parse_args()

    west, south, east, north = map(float, args.bbox.split(","))
    geojson = fetch_lcsfproj((west, south, east, north))
    print(f"Fetched {len(geojson.get('features', []))} features")
    features_to_obj(geojson, args.height, args.out)
