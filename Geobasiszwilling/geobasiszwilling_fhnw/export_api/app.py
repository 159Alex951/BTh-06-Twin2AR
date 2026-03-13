import json
import gzip
import math
import os
import re
import shutil
import subprocess
import tempfile
import struct
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file
#new
from pyproj import Transformer
_ecef_to_wgs84 = Transformer.from_crs("EPSG:4978", "EPSG:4326", always_xy=True)
#end new

app = Flask(__name__)

# We export from already-generated 3D Tiles GLB contents.
# The output folder is mounted into the container via docker-compose.
OUTPUT_DIR = Path(os.getenv("EXPORT_OUTPUT_DIR", "/data/output")).resolve()
BUILDINGS_BFS_TILESET = OUTPUT_DIR / "buildings_bfs" / "tileset.json"
BUILDINGS_BFS_CONTENT_DIR = OUTPUT_DIR / "buildings_bfs" / "content"

TERRAIN_QM_DIR = OUTPUT_DIR / "terrain_qm"
TERRAIN_QM_ALT_DIR = OUTPUT_DIR / "_terrain_qm"

# EPSG:4326 global tile bounds used by quantized-mesh TMS: lon in [-180, 180], lat in [-90, 90].
WORLD_BOUNDS_EPSG4326 = (-180.0, -90.0, 180.0, 90.0)


def _safe_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "buildings.obj"
    # Keep it very conservative
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    if not name.lower().endswith(".obj"):
        name += ".obj"
    return name


def _parse_poly(poly_raw: str):
    try:
        coords = json.loads(poly_raw)
    except Exception as exc:
        raise ValueError("poly must be JSON") from exc

    if not isinstance(coords, list) or len(coords) < 4:
        raise ValueError("poly must be an array with at least 4 points")

    points = []
    for item in coords:
        if (
            not isinstance(item, (list, tuple))
            or len(item) < 2
            or not isinstance(item[0], (int, float))
            or not isinstance(item[1], (int, float))
        ):
            raise ValueError("poly points must be [lon, lat]")
        lon = float(item[0])
        lat = float(item[1])
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("poly lon/lat out of range")
        points.append((lon, lat))

    # Use first 4 points only (rectangle footprint)
    points = points[:4]

    # Close ring
    if points[0] != points[-1]:
        points.append(points[0])

    return points


def _wkt_polygon(points):
    # points are validated floats -> safe string formatting
    coord_str = ", ".join([f"{lon:.10f} {lat:.10f}" for lon, lat in points])
    return f"POLYGON(({coord_str}))"


def _load_tileset_root_region():
    if not BUILDINGS_BFS_TILESET.exists():
        raise FileNotFoundError(f"tileset.json not found at {BUILDINGS_BFS_TILESET}")

    data = json.loads(BUILDINGS_BFS_TILESET.read_text(encoding="utf-8"))
    root = data.get("root") or {}
    bv = root.get("boundingVolume") or {}
    region = bv.get("region")
    if not (isinstance(region, list) and len(region) >= 4):
        raise ValueError("tileset root boundingVolume.region missing")
    west, south, east, north = map(float, region[:4])
    return west, south, east, north


def _load_buildings_root_origin_ecef():
    # Buildings content GLBs are positioned by tileset root.transform.
    # We export OBJs from raw GLBs (without applying the tileset transform), so their
    # vertex coordinates are effectively in a local frame centered at that origin.
    if not BUILDINGS_BFS_TILESET.exists():
        return 0.0, 0.0, 0.0

    try:
        data = json.loads(BUILDINGS_BFS_TILESET.read_text(encoding="utf-8"))
        root = data.get("root") or {}
        tfm = root.get("transform")
        if isinstance(tfm, list) and len(tfm) >= 16:
            # 3D Tiles transforms are column-major; translation is indices 12..14.
            return float(tfm[12]), float(tfm[13]), float(tfm[14])
    except Exception:
        pass

    return 0.0, 0.0, 0.0


def _find_terrain_dir() -> Path:
    if TERRAIN_QM_DIR.exists():
        return TERRAIN_QM_DIR
    if TERRAIN_QM_ALT_DIR.exists():
        return TERRAIN_QM_ALT_DIR
    raise FileNotFoundError("terrain_qm directory not found in output")


def _terrain_available_zooms(terrain_dir: Path):
    zooms = []
    for child in terrain_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            zooms.append(int(child.name))
        except ValueError:
            continue
    return sorted(zooms)


def _wgs84_to_ecef(lon_rad: float, lat_rad: float, height_m: float):
    # WGS84
    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)

    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)

    n = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)
    x = (n + height_m) * cos_lat * cos_lon
    y = (n + height_m) * cos_lat * sin_lon
    z = ((1.0 - e2) * n + height_m) * sin_lat
    return x, y, z


def _ecef_to_lon_lat(x: float, y: float, z: float):
    # WGS84 inverse for lon/lat (radians). Height not needed.
    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    b = a * (1.0 - f)

    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    if p == 0.0:
        lat = math.copysign(math.pi / 2.0, z)
        return lon, lat

    # Initial guess (Bowring)
    theta = math.atan2(z * a, p * b)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)
    lat = math.atan2(z + (e2 * b) * sin_t * sin_t * sin_t, p - (e2 * a) * cos_t * cos_t * cos_t)
    return lon, lat


def _ecef_delta_to_enu(dx: float, dy: float, dz: float, lon0: float, lat0: float):
    sin_lon = math.sin(lon0)
    cos_lon = math.cos(lon0)
    sin_lat = math.sin(lat0)
    cos_lat = math.cos(lat0)

    # ECEF -> ENU at origin (lon0, lat0)
    e = -sin_lon * dx + cos_lon * dy
    n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    u = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    return e, n, u


def _translate_obj_to_origin_raw(obj_path: Path):
    """Translate OBJ geometry so it starts at a stable local origin.

    This intentionally applies **no rotation** and no coordinate-frame conversion.
    It only:
    - centers XY on the combined model bounding box center
    - shifts Z so minZ becomes 0

    This is useful when upstream meshes (buildings + terrain) are already in the same
    raw coordinate frame and we only want a (0,0,0) placement for DCC tools.
    """

    minx = miny = minz = float("inf")
    maxx = maxy = maxz = float("-inf")

    with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("v "):
                continue
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            try:
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
            except Exception:
                continue
            minx = min(minx, x)
            miny = min(miny, y)
            minz = min(minz, z)
            maxx = max(maxx, x)
            maxy = max(maxy, y)
            maxz = max(maxz, z)

    if minx == float("inf"):
        return

    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    gz = minz

    tmp_path = obj_path.with_suffix(".translated.obj")

    with obj_path.open("r", encoding="utf-8", errors="ignore") as src, tmp_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        x = float(parts[1])
                        y = float(parts[2])
                        z = float(parts[3])
                        x -= cx
                        y -= cy
                        z -= gz
                        dst.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
                        continue
                    except Exception:
                        pass
            dst.write(line)

    tmp_path.replace(obj_path)


def _normalize_obj_to_enu_for_dcc(obj_path: Path, origin_ecef):
    """Optional: rewrite OBJ into a local ENU frame at `origin_ecef`.

    This performs a rotation (ECEF -> ENU) in addition to translation, which some DCC
    tools/users may perceive as "verdreht" depending on import axis settings.
    """

    ox, oy, oz = map(float, origin_ecef)
    lon0, lat0 = _ecef_to_lon_lat(ox, oy, oz)

    minx = miny = minz = float("inf")
    maxx = maxy = maxz = float("-inf")

    def to_enu(x: float, y: float, z: float):
        return _ecef_delta_to_enu(x, y, z, lon0, lat0)

    with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("v "):
                continue
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            try:
                x = float(parts[1])
                y = float(parts[2])
                z = float(parts[3])
            except Exception:
                continue
            ex, ny, up = to_enu(x, y, z)
            minx = min(minx, ex)
            miny = min(miny, ny)
            minz = min(minz, up)
            maxx = max(maxx, ex)
            maxy = max(maxy, ny)
            maxz = max(maxz, up)

    if minx == float("inf"):
        return

    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    gz = minz

    tmp_path = obj_path.with_suffix(".enu.obj")

    with obj_path.open("r", encoding="utf-8", errors="ignore") as src, tmp_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        x = float(parts[1])
                        y = float(parts[2])
                        z = float(parts[3])
                        ex, ny, up = to_enu(x, y, z)
                        ex -= cx
                        ny -= cy
                        up -= gz
                        dst.write(f"v {ex:.6f} {ny:.6f} {up:.6f}\n")
                        continue
                    except Exception:
                        pass
            if line.startswith("vn "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        x = float(parts[1])
                        y = float(parts[2])
                        z = float(parts[3])
                        ex, ny, up = to_enu(x, y, z)
                        dst.write(f"vn {ex:.6f} {ny:.6f} {up:.6f}\n")
                        continue
                    except Exception:
                        pass
            dst.write(line)

    tmp_path.replace(obj_path)

#new
def _normalize_obj_to_wgs84(obj_path: Path, origin_ecef):
    """Rewrite OBJ vertices into WGS84 (lon, lat, height).
    X = longitude (degrees), Y = latitude (degrees), Z = ellipsoidal height (meters).
    Also writes a companion .json file next to the OBJ with the anchor point
    (centroid in WGS84) so ARCore can place a Geospatial Anchor.
    """
    ox, oy, oz = map(float, origin_ecef)

    # First pass: collect all converted vertices to find the centroid
    vertices = []
    with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.startswith("v "):
                continue
            parts = line.strip().split()
            if len(parts) < 4:
                continue
            try:
                vx = float(parts[1]) + ox
                vy = float(parts[2]) + oy
                vz = float(parts[3]) + oz
                lon, lat, h = _ecef_to_wgs84.transform(vx, vy, vz)
                vertices.append((lon, lat, h))
            except Exception:
                continue

    if not vertices:
        return

    # Compute anchor = centroid of all vertices
    anchor_lon = sum(v[0] for v in vertices) / len(vertices)
    anchor_lat = sum(v[1] for v in vertices) / len(vertices)
    anchor_h   = sum(v[2] for v in vertices) / len(vertices)

    # Write companion anchor JSON for the AR app
    anchor_path = obj_path.with_suffix(".anchor.json")
    anchor_path.write_text(
        json.dumps({"longitude": anchor_lon, "latitude": anchor_lat, "altitude": anchor_h}),
        encoding="utf-8"
    )

    # Second pass: rewrite OBJ with WGS84 coords as local ENU offsets (meters) from anchor
    # This keeps vertex numbers small and metric — ideal for ARCore mesh rendering
    import math
    sin_lon = math.sin(math.radians(anchor_lon))
    cos_lon = math.cos(math.radians(anchor_lon))
    sin_lat = math.sin(math.radians(anchor_lat))
    cos_lat = math.cos(math.radians(anchor_lat))

    def _to_local_enu(lon_deg, lat_deg, h_m):
        # Convert WGS84 -> ECEF -> ENU offset from anchor (in meters)
        vx, vy, vz = _ecef_to_wgs84.transform(lon_deg, lat_deg, h_m, direction="INVERSE")
        ax, ay, az = _ecef_to_wgs84.transform(anchor_lon, anchor_lat, anchor_h, direction="INVERSE")
        dx, dy, dz = vx - ax, vy - ay, vz - az
        e = -sin_lon * dx + cos_lon * dy
        n = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
        u =  cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
        return e, n, u

    tmp_path = obj_path.with_suffix(".wgs84.obj")
    with obj_path.open("r", encoding="utf-8", errors="ignore") as src, \
         tmp_path.open("w", encoding="utf-8") as dst:
        vi = 0
        for line in src:
            if line.startswith("v "):
                parts = line.strip().split()
                if len(parts) >= 4:
                    try:
                        lon, lat, h = vertices[vi]
                        e, n, u = _to_local_enu(lon, lat, h)
                        dst.write(f"v {e:.4f} {n:.4f} {u:.4f}\n")
                        vi += 1
                        continue
                    except Exception:
                        pass
            dst.write(line)

    tmp_path.replace(obj_path)
#end new

def _zigzag_decode(u16: int) -> int:
    return (u16 >> 1) ^ (-(u16 & 1))


def _decode_highwater_indices(encoded_u16):
    highest = 0
    out = []
    for code in encoded_u16:
        idx = highest - int(code)
        out.append(idx)
        if code == 0:
            highest += 1
    return out


def _read_u16_array(buf: bytes, offset: int, count: int):
    size = 2 * count
    arr = struct.unpack_from(f"<{count}H", buf, offset)
    return arr, offset + size


def _decode_quantized_mesh_tile(
    tile_path: Path,
    z: int,
    x: int,
    y: int,
    bounds,
    origin_ecef=(0.0, 0.0, 0.0),
):
    # Cesium Quantized-Mesh 1.0 decoder (core mesh only).
    data = tile_path.read_bytes()
    # Many terrain servers store quantized-mesh payload gzipped, but keep the .terrain extension.
    # Detect gzip magic and decompress.
    if len(data) >= 3 and data[0:3] == b"\x1f\x8b\x08":
        data = gzip.decompress(data)
    off = 0

    # Header (88 bytes)
    center_x, center_y, center_z = struct.unpack_from("<ddd", data, off)
    off += 24
    min_h, max_h = struct.unpack_from("<ff", data, off)
    off += 8
    # boundingSphere (ignored)
    off += 24
    off += 8
    # horizonOcclusionPoint (ignored)
    off += 24

    (vertex_count,) = struct.unpack_from("<I", data, off)
    off += 4
    if vertex_count <= 0:
        return [], []

    u_buf, off = _read_u16_array(data, off, vertex_count)
    v_buf, off = _read_u16_array(data, off, vertex_count)
    h_buf, off = _read_u16_array(data, off, vertex_count)

    # Delta + zigzag decode
    u_vals = []
    v_vals = []
    h_vals = []
    u_acc = 0
    v_acc = 0
    h_acc = 0
    for i in range(vertex_count):
        u_acc += _zigzag_decode(u_buf[i])
        v_acc += _zigzag_decode(v_buf[i])
        h_acc += _zigzag_decode(h_buf[i])
        u_vals.append(u_acc)
        v_vals.append(v_acc)
        h_vals.append(h_acc)

    # Quantized-mesh stores triangleCount (not indexCount). Indices are 3 * triangleCount.
    (triangle_count,) = struct.unpack_from("<I", data, off)
    off += 4
    if triangle_count <= 0:
        return [], []

    index_count = int(triangle_count) * 3
    enc_indices, off = _read_u16_array(data, off, index_count)
    indices = _decode_highwater_indices(enc_indices)
    if len(indices) % 3 != 0:
        indices = indices[: (len(indices) // 3) * 3]

    # Skip edge indices blocks
    for _ in range(4):
        (edge_count,) = struct.unpack_from("<I", data, off)
        off += 4
        off += 2 * int(edge_count)

    # Compute tile rectangle in EPSG:4326, schema=TMS.
    # In EPSG:4326 tiling, the X dimension covers 360° and uses 2^(z+1) tiles,
    # while Y covers 180° and uses 2^z tiles.
    bw, bs, be, bn = WORLD_BOUNDS_EPSG4326
    nx = 2 ** (int(z) + 1)
    ny = 2 ** int(z)
    lon_span = (be - bw) / nx
    lat_span = (bn - bs) / ny
    west = bw + x * lon_span
    east = west + lon_span
    south = bs + y * lat_span
    north = south + lat_span

    # Quantized range in spec: 0..32767
    qmax = 32767.0
    ox, oy, oz = map(float, origin_ecef)
    vertices = []
    for i in range(vertex_count):
        uu = float(u_vals[i]) / qmax
        vv = float(v_vals[i]) / qmax
        hh = float(h_vals[i]) / qmax

        lon_deg = west + uu * (east - west)
        lat_deg = south + vv * (north - south)
        height_m = float(min_h) + hh * (float(max_h) - float(min_h))

        lon_rad = math.radians(lon_deg)
        lat_rad = math.radians(lat_deg)
        px, py, pz = _wgs84_to_ecef(lon_rad, lat_rad, height_m)

        # Emit ECEF delta relative to buildings origin. We'll normalize the final OBJ
        # into ENU + grounded/centered coordinates in one common post-step.
        vertices.append((px - ox, py - oy, pz - oz))

    return vertices, indices


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _tms_xy_range_for_bbox_deg(
    west_deg: float,
    south_deg: float,
    east_deg: float,
    north_deg: float,
    z: int,
    bounds=(0.0, -90.0, 180.0, 90.0),
):
    # layer.json declares EPSG:4326, schema=tms, bounds=[0,-90,180,90]
    bw, bs, be, bn = map(float, bounds)
    if be <= bw or bn <= bs:
        raise ValueError("invalid terrain bounds")

    # Clamp query into dataset bounds
    west = max(bw, min(be, float(west_deg)))
    east = max(bw, min(be, float(east_deg)))
    south = max(bs, min(bn, float(south_deg)))
    north = max(bs, min(bn, float(north_deg)))

    if east < west:
        west, east = east, west
    if north < south:
        south, north = north, south

    # EPSG:4326 TMS has 2^(z+1) tiles in X (360°) and 2^z tiles in Y (180°).
    # Indices are based on the global extent [-180,180]x[-90,90], even if the
    # dataset only covers a subset (e.g. bounds [0,180]).
    wx0, wy0, wx1, wy1 = WORLD_BOUNDS_EPSG4326
    nx = 2 ** (int(z) + 1)
    ny = 2 ** int(z)

    def lon_to_x(lon):
        return int(math.floor(nx * (lon - wx0) / (wx1 - wx0)))

    def lat_to_y(lat):
        # TMS origin is bottom-left (south)
        return int(math.floor(ny * (lat - wy0) / (wy1 - wy0)))

    x0 = _clamp(lon_to_x(west), 0, nx - 1)
    x1 = _clamp(lon_to_x(east), 0, nx - 1)
    y0 = _clamp(lat_to_y(south), 0, ny - 1)
    y1 = _clamp(lat_to_y(north), 0, ny - 1)

    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0

    return x0, x1, y0, y1


def _terrain_tile_path(terrain_dir: Path, z: int, x: int, y: int) -> Path:
    return terrain_dir / str(int(z)) / str(int(x)) / f"{int(y)}.terrain"


def _collect_terrain_tiles_for_bbox(points_deg, max_tiles=5000):
    return _collect_terrain_tiles_for_bbox_impl(points_deg, include_ancestors=True, max_tiles=max_tiles)


def _collect_terrain_tiles_for_bbox_impl(points_deg, include_ancestors: bool, max_tiles=5000):
    # points_deg: list[(lon,lat)] closed ring
    lons = [p[0] for p in points_deg]
    lats = [p[1] for p in points_deg]
    west_deg = min(lons)
    east_deg = max(lons)
    south_deg = min(lats)
    north_deg = max(lats)

    terrain_dir = _find_terrain_dir()
    zooms = _terrain_available_zooms(terrain_dir)
    if not zooms:
        raise FileNotFoundError("No zoom directories found in terrain_qm")
    # Prefer the highest zoom that actually has tiles for this bbox.
    # Some pipelines create empty zoom directories (e.g. 17/) which would otherwise
    # cause us to select nothing.
    zooms = sorted(zooms, reverse=True)

    # Try to read bounds from layer.json, fallback to default
    bounds = (0.0, -90.0, 180.0, 90.0)
    layer_json = terrain_dir / "layer.json"
    if layer_json.exists():
        try:
            data = json.loads(layer_json.read_text(encoding="utf-8"))
            b = data.get("bounds")
            if isinstance(b, list) and len(b) == 4:
                bounds = tuple(map(float, b))
        except Exception:
            pass

    selected = set()
    chosen_z = None
    x0 = x1 = y0 = y1 = None
    for z_try in zooms:
        x0_try, x1_try, y0_try, y1_try = _tms_xy_range_for_bbox_deg(
            west_deg, south_deg, east_deg, north_deg, z=z_try, bounds=bounds
        )
        candidate = set()
        for x in range(x0_try, x1_try + 1):
            for y in range(y0_try, y1_try + 1):
                p = _terrain_tile_path(terrain_dir, z_try, x, y)
                if p.exists():
                    candidate.add((z_try, x, y))
                if len(candidate) > max_tiles:
                    raise ValueError("Too many terrain tiles selected; export box too large")

        if candidate:
            selected = candidate
            chosen_z = z_try
            x0, x1, y0, y1 = x0_try, x1_try, y0_try, y1_try
            break

    if not selected:
        return {
            "terrain_dir": terrain_dir,
            "layer_json": layer_json if layer_json.exists() else None,
            "zoom_max": max(zooms),
            "bounds": bounds,
            "x_range": [0, -1],
            "y_range": [0, -1],
            "tiles": [],
        }

    expanded = set(selected)
    if include_ancestors:
        for tz, tx, ty in list(selected):
            cz, cx, cy = tz, tx, ty
            while cz > 0:
                cz -= 1
                cx //= 2
                cy //= 2
                p = _terrain_tile_path(terrain_dir, cz, cx, cy)
                if p.exists():
                    expanded.add((cz, cx, cy))
                if len(expanded) > max_tiles:
                    break

    return {
        "terrain_dir": terrain_dir,
        "layer_json": layer_json if layer_json.exists() else None,
        "zoom_max": int(chosen_z) if chosen_z is not None else max(zooms),
        "bounds": bounds,
        "x_range": [x0, x1],
        "y_range": [y0, y1],
        "tiles": sorted(expanded),
    }


def _append_terrain_to_obj(obj_path: Path, points_deg, max_tiles=250):
    # Append terrain as additional groups to an existing OBJ.
    # For OBJ merging we only need to offset vertex indices.

    # Determine current vertex count in OBJ
    v_total = 0
    with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                v_total += 1

    terrain_info = _collect_terrain_tiles_for_bbox_impl(
        points_deg, include_ancestors=False, max_tiles=max_tiles
    )
    terrain_dir: Path = terrain_info["terrain_dir"]
    bounds = terrain_info["bounds"]
    tiles = terrain_info["tiles"]
    if not tiles:
        return 0

    origin_ecef = _load_buildings_root_origin_ecef()

    appended_tiles = 0
    with obj_path.open("a", encoding="utf-8") as out:
        out.write("\n# Terrain (quantized-mesh) appended\n")
        for z, x, y in tiles:
            tile_path = _terrain_tile_path(terrain_dir, z, x, y)
            if not tile_path.exists():
                continue
            try:
                vertices, indices = _decode_quantized_mesh_tile(
                    tile_path, z, x, y, bounds=bounds, origin_ecef=origin_ecef
                )
            except Exception:
                # Skip tiles we can't decode; keep the export usable.
                continue
            if not vertices or not indices:
                continue

            out.write(f"\ng terrain_{z}_{x}_{y}\n")
            for vx, vy, vz in vertices:
                out.write(f"v {vx:.6f} {vy:.6f} {vz:.6f}\n")

            # Faces (1-based OBJ indices)
            for i in range(0, len(indices), 3):
                a = v_total + indices[i] + 1
                b = v_total + indices[i + 1] + 1
                c = v_total + indices[i + 2] + 1
                out.write(f"f {a} {b} {c}\n")

            v_total += len(vertices)
            appended_tiles += 1

    return appended_tiles


def _poly_bbox_radians(points_deg):
    lons = [p[0] for p in points_deg]
    lats = [p[1] for p in points_deg]
    west = math.radians(min(lons))
    east = math.radians(max(lons))
    south = math.radians(min(lats))
    north = math.radians(max(lats))
    return west, south, east, north


def _tile_region(root_region, level: int, x: int, y: int):
    root_w, root_s, root_e, root_n = root_region
    divisions = 2**level
    dlon = (root_e - root_w) / divisions
    dlat = (root_n - root_s) / divisions
    tw = root_w + x * dlon
    te = root_w + (x + 1) * dlon
    ts = root_s + y * dlat
    tn = root_s + (y + 1) * dlat
    return tw, ts, te, tn


def _regions_intersect(a, b):
    aw, as_, ae, an = a
    bw, bs, be, bn = b
    return not (ae < bw or be < aw or an < bs or bn < as_)


def _list_content_tiles():
    if not BUILDINGS_BFS_CONTENT_DIR.exists():
        return []
    tiles = []
    for p in BUILDINGS_BFS_CONTENT_DIR.glob("*.glb"):
        m = re.match(r"^(\d+)_(\d+)_(\d+)\.glb$", p.name)
        if not m:
            continue
        level = int(m.group(1))
        x = int(m.group(2))
        y = int(m.group(3))
        tiles.append((level, x, y, p))
    return tiles


def _merge_objs(obj_paths, out_path: Path):
    v_offset = 0
    vt_offset = 0
    vn_offset = 0

    with out_path.open("w", encoding="utf-8") as out:
        out.write("# Exported from buildings_bfs tiles\n")

        for obj_path in obj_paths:
            out.write(f"\ng {obj_path.stem}\n")
            with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("mtllib") or line.startswith("usemtl"):
                        continue
                    if line.startswith("v "):
                        out.write(line)
                        v_offset += 1
                        continue
                    if line.startswith("vt "):
                        out.write(line)
                        vt_offset += 1
                        continue
                    if line.startswith("vn "):
                        out.write(line)
                        vn_offset += 1
                        continue

            # Second pass for faces (need offsets from *previous* totals, so track separately)
            # We'll re-read and rewrite faces with index shifts.
            # To do that, we need the counts BEFORE writing this file's vertices.
            # So we compute counts by scanning once up front.

        # The above increments offsets as we go, but we need proper index shifts per file.
    
    # Re-implement with proper per-file offsets
    v_total = 0
    vt_total = 0
    vn_total = 0
    with out_path.open("w", encoding="utf-8") as out:
        out.write("# Exported from buildings_bfs tiles\n")
        for obj_path in obj_paths:
            v_count = 0
            vt_count = 0
            vn_count = 0
            with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("v "):
                        v_count += 1
                    elif line.startswith("vt "):
                        vt_count += 1
                    elif line.startswith("vn "):
                        vn_count += 1

            out.write(f"\ng {obj_path.stem}\n")
            with obj_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("mtllib") or line.startswith("usemtl"):
                        continue
                    if line.startswith("v ") or line.startswith("vt ") or line.startswith("vn "):
                        out.write(line)
                        continue
                    if line.startswith("f "):
                        parts = line.strip().split()[1:]
                        new_parts = []
                        for part in parts:
                            # formats: v, v/vt, v//vn, v/vt/vn
                            comps = part.split("/")
                            if len(comps) >= 1 and comps[0]:
                                comps[0] = str(int(comps[0]) + v_total)
                            if len(comps) >= 2 and comps[1]:
                                comps[1] = str(int(comps[1]) + vt_total)
                            if len(comps) == 3 and comps[2]:
                                comps[2] = str(int(comps[2]) + vn_total)
                            new_parts.append("/".join(comps))
                        out.write("f " + " ".join(new_parts) + "\n")
                        continue

            v_total += v_count
            vt_total += vt_count
            vn_total += vn_count


def _export_buildings_obj_to_tmp(points_deg, tmpdir: str):
    root_region = _load_tileset_root_region()
    query_bbox = _poly_bbox_radians(points_deg)

    content_tiles = _list_content_tiles()
    if not content_tiles:
        raise FileNotFoundError("No buildings_bfs content tiles found")

    selected = []
    for level, x, y, path in content_tiles:
        tile_reg = _tile_region(root_region, level, x, y)
        if _regions_intersect(tile_reg, query_bbox):
            selected.append((level, x, y, path))

    if not selected:
        raise FileNotFoundError("No tiles intersect export box")

    obj_paths = []
    for level, x, y, glb_path in selected:
        out_obj_tile = Path(tmpdir) / f"tile_{level}_{x}_{y}.obj"
        assimp_cmd = ["assimp", "export", str(glb_path), str(out_obj_tile), "-f", "obj"]
        proc = subprocess.run(
            assimp_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0 or not out_obj_tile.exists():
            raise RuntimeError(
                "GLB to OBJ conversion failed: "
                + ((proc.stderr or proc.stdout) or "").strip()[-4000:]
            )
        obj_paths.append(out_obj_tile)

    merged_obj = Path(tmpdir) / "buildings.obj"
    _merge_objs(obj_paths, merged_obj)
    if merged_obj.stat().st_size < 50:
        raise FileNotFoundError("No geometry exported")

    return merged_obj, len(selected)

#new prjektierte Gebäude extrudieren
import requests

@app.get("/export/projected_buildings.geojson")
def projected_buildings_geojson():
    lon_center = float(request.args.get("lon", 7.637))
    lat_center = float(request.args.get("lat", 47.531))

    dlat = 0.18
    dlon = 0.27

    west  = lon_center - dlon
    east  = lon_center + dlon
    south = lat_center - dlat
    north = lat_center + dlat

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "ms:LCSFPROJ",
        "OUTPUTFORMAT": "application/json; subtype=geojson",
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326",
        "COUNT": 5000,
    }
    try:
        r = requests.get("https://geodienste.ch/db/av_0/deu", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        return jsonify({"error": "WFS request failed", "details": str(exc)}), 502

    for feat in data.get("features", []):
        props = feat.setdefault("properties", {})
        props.setdefault("height", 10.0)

    return jsonify(data)


#end new

@app.get("/export/health")
def health():
    return jsonify({"ok": True})


@app.get("/export/buildings.obj")
def export_buildings_obj():
    poly_raw = request.args.get("poly", "")
    filename = _safe_filename(request.args.get("filename"))

    if not poly_raw:
        return jsonify({"error": "Missing required query param: poly"}), 400

    try:
        points = _parse_poly(poly_raw)
        wkt = _wkt_polygon(points)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Select GLB content tiles that intersect the drawn polygon bbox.
    tmpdir = tempfile.mkdtemp(prefix="export_obj_")
    try:
        merged_obj, tiles_count = _export_buildings_obj_to_tmp(points, tmpdir)

        # Append terrain into same OBJ
        try:
            terrain_tiles_appended = _append_terrain_to_obj(merged_obj, points)
        except FileNotFoundError:
            terrain_tiles_appended = 0
        except Exception as exc:
            return jsonify({"error": "Terrain export failed", "details": str(exc)[-4000:]}), 500

        # Final placement for DCC tools (Blender).
        # By default we apply translation only (no rotation/frame conversion): center XY and set minZ=0.
        # Optional: `normalize=enu` to rotate into a local ENU frame at the buildings origin.
        normalize_mode = (request.args.get("normalize", "wgs84") or "wgs84").strip().lower()
        try:
            if normalize_mode == "enu":
                origin_ecef = _load_buildings_root_origin_ecef()
                _normalize_obj_to_enu_for_dcc(merged_obj, origin_ecef)
            elif normalize_mode == "wgs84":                             # ← new
                origin_ecef = _load_buildings_root_origin_ecef()        # ← new
                _normalize_obj_to_wgs84(merged_obj, origin_ecef)       # ← new
            elif normalize_mode in ("raw", "none", "0"):
                _translate_obj_to_origin_raw(merged_obj)
            else:
                _translate_obj_to_origin_raw(merged_obj)
        except Exception:
            # Keep export usable even if normalization fails.
            pass

        import zipfile
        zip_path = Path(tmpdir) / "export.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(merged_obj, filename)
            anchor_json = merged_obj.with_suffix(".anchor.json")
            if anchor_json.exists():
                zf.write(anchor_json, "anchor.json")

        resp = send_file(
            str(zip_path),
            as_attachment=True,
            download_name="export.zip",
            mimetype="application/zip",
            max_age=0,
        )
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Export-Timestamp"] = datetime.now(timezone.utc).isoformat()
        resp.headers["X-Export-Tiles-Count"] = str(tiles_count)
        resp.headers["X-Export-Terrain-Tiles-Count"] = str(terrain_tiles_appended)
        return resp

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Export timed out"}), 504
    except Exception as exc:
        return jsonify({"error": "Internal export error", "details": str(exc)}), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
#new
@app.get("/export/scene.zip")
def export_scene_zip():
    poly_raw = request.args.get("poly", "")
    if not poly_raw:
        return jsonify({"error": "Missing required query param: poly"}), 400

    try:
        points = _parse_poly(poly_raw)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    tmpdir = tempfile.mkdtemp(prefix="export_scene_")
    try:
        # 1) existing buildings + terrain as today
        merged_obj, tiles_count = _export_buildings_obj_to_tmp(points, tmpdir)
        _append_terrain_to_obj(merged_obj, points)

        # 2) compute shared anchor (centroid of bbox in WGS84)
        lons = [p[0] for p in points]
        lats = [p[1] for p in points]
        anchor_lon = sum(lons) / len(lons)
        anchor_lat = sum(lats) / len(lats)
        anchor_alt = 0.0  # later: sample terrain

        anchor_path = Path(tmpdir) / "anchor.json"
        anchor_path.write_text(
            json.dumps({
                "longitude": anchor_lon,
                "latitude": anchor_lat,
                "altitude": anchor_alt,
            }),
            encoding="utf-8",
        )

        # 3) generate projected buildings OBJ in same ENU system
        proj_obj = Path(tmpdir) / "projected_buildings.obj"
        _export_projected_buildings_obj(points, proj_obj, anchor_lon, anchor_lat, anchor_alt)

        # 4) zip everything
        zip_path = Path(tmpdir) / "scene.zip"
        import zipfile
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(merged_obj, "buildings.obj")
            zf.write(proj_obj, "projected_buildings.obj")
            zf.write(anchor_path, "anchor.json")

        resp = send_file(
            str(zip_path),
            as_attachment=True,
            download_name="scene.zip",
            mimetype="application/zip",
            max_age=0,
        )
        resp.headers["Cache-Control"] = "no-store"
        return resp

    except Exception as exc:
        return jsonify({"error": "Internal scene export error", "details": str(exc)}), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
#end new