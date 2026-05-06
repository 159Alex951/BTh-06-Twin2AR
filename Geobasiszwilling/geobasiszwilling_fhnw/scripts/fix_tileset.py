import json
import math
from pathlib import Path

try:
    from pyproj import Transformer
except ImportError:
    print("Error: pyproj not found. Make sure you run this in your virtual environment.")
    exit(1)

def main():
    # The output directory where the problematic tileset is
    out_dir = Path(r"D:\Unity\REALBACKEND\BTh-06-Twin2AR\Geobasiszwilling\geobasiszwilling_fhnw\output\buildings_bfs_400m_glb_1")
    tileset_file = out_dir / "tileset.json"
    anchor_file = out_dir / "anchor.json"

    if not tileset_file.exists() or not anchor_file.exists():
        print("Could not find tileset.json or anchor.json in:", out_dir)
        return

    # 1. Read the anchor coordinates
    with open(anchor_file, "r") as f:
        anchor = json.load(f)

    lon = anchor["longitude"]
    lat = anchor["latitude"]
    alt = anchor.get("altitude", 0.0)

    print(f"Loaded anchor: lon={lon}, lat={lat}, alt={alt}")

    # 2. Compute the exact standard ENU-to-ECEF matrix
    wgs84_to_ecef = Transformer.from_crs("EPSG:4326", "EPSG:4978", always_xy=True)
    ax, ay, az = wgs84_to_ecef.transform(lon, lat, alt)

    sin_lon = math.sin(math.radians(lon))
    cos_lon = math.cos(math.radians(lon))
    sin_lat = math.sin(math.radians(lat))
    cos_lat = math.cos(math.radians(lat))

    # This is the pure ENU-to-ECEF matrix without the manual Rx(-90) rotation flip
    correct_enu_to_ecef = [
        -sin_lon,          cos_lon,          0.0,      0.0,
        -sin_lat*cos_lon, -sin_lat*sin_lon,  cos_lat,  0.0,
         cos_lat*cos_lon,  cos_lat*sin_lon,  sin_lat,  0.0,
         ax,               ay,               az,       1.0
    ]

    # 3. Read the tileset and overwrite the root transform
    with open(tileset_file, "r") as f:
        tileset = json.load(f)

    old_transform = tileset["root"].get("transform", [])
    tileset["root"]["transform"] = correct_enu_to_ecef

    # 4. Save it back
    with open(tileset_file, "w") as f:
        json.dump(tileset, f, indent=2)

    print("Patch applied! tileset.json 'root.transform' updated successfully.")

if __name__ == "__main__":
    main()
