from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import cv2
import numpy as np
import os
import glob
import io
import json
import math
import re
import time
import shutil
import zipfile

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(BASE_DIR, "test_data", "inputs")
SELECT_DIR = os.path.join(BASE_DIR, "test_data", "selections")
MAP_PATH = os.path.join(BASE_DIR, "map.html")

# Correct Relative Path Calculation:
# BASE_DIR evaluates to: .../BTh-06-Twin2AR/Twin2AR/Frontend
# We go up 2 levels back to root (BTh-06-Twin2AR), then down into the target
OUTPUT_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "Geobasiszwilling", "geobasiszwilling_fhnw", "output"))

# Standard Directories
os.makedirs(TEST_DIR, exist_ok=True)
os.makedirs(SELECT_DIR, exist_ok=True)

# Let FastAPI crash on startup if the directory is completely missing.
# If this crashes Docker, it means your docker-compose.yml volume mount is missing or wrong!
if not os.path.exists(OUTPUT_DIR):
    raise RuntimeError(f"CRITICAL ERROR: Tile directory missing! {OUTPUT_DIR} does not exist in this container. Mount it in docker-compose.yml!")

app.mount("/data", StaticFiles(directory=TEST_DIR), name="data")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/check-tiles")
async def check_tiles():
    # Append content to the check since that's where the actual files are!
    glb_dir = os.path.join(OUTPUT_DIR, "buildings_bfs_400m_glb", "content")
    if not os.path.exists(glb_dir):
        return {"error": f"Directory not found: {glb_dir}"}
        
    files = glob.glob(os.path.join(glb_dir, "*.glb"))
    return {
        "status": "success",
        "output_path_used": OUTPUT_DIR,
        "total_glb_files_found": len(files),
        "sample_files": [os.path.basename(f) for f in files[:5]]
    }
@app.get("/api/locations")
async def get_locations():
    """Lightweight listing used by the sidebar (polled every 5 s).
    Reuses the shared file-walker so /api/stats and this endpoint stay in lockstep."""
    return [
        {
            "filename":  e["filename"],
            "selected":  e["selected"],
            "has_image": e["has_image"],
        }
        for e in _list_pose_files(newest_first=True)
    ]


def _list_pose_files(newest_first=True):
    """Single source of truth for enumerating saved pose JSONs in TEST_DIR.
    Adds the on-disk mtime and the matching .jpg / selection-flag once, so the
    statistics endpoint and the sidebar endpoint never disagree."""
    files = glob.glob(os.path.join(TEST_DIR, "*.json"))
    files.sort(key=os.path.getmtime, reverse=newest_first)
    out = []
    for path in files:
        filename = os.path.basename(path)
        jpg_name = filename[:-5] + ".jpg"
        out.append({
            "path":      path,
            "filename":  filename,
            "mtime":     os.path.getmtime(path),
            "jpg_name":  jpg_name,
            "jpg_path":  os.path.join(TEST_DIR, jpg_name),
            "selected":  os.path.exists(os.path.join(SELECT_DIR, filename)),
            "has_image": os.path.exists(os.path.join(TEST_DIR, jpg_name)),
        })
    return out

@app.post("/api/select")
async def select_location(request: Request):
    data = await request.json()
    filename = data.get("filename")
    selected = data.get("selected", False)

    if not filename or not filename.endswith(".json"):
        return {"status": "error", "message": "invalid filename"}

    json_src = os.path.join(TEST_DIR, filename)
    jpg_name = filename[:-5] + ".jpg"
    jpg_src = os.path.join(TEST_DIR, jpg_name)

    json_dst = os.path.join(SELECT_DIR, filename)
    jpg_dst = os.path.join(SELECT_DIR, jpg_name)

    try:
        if selected:
            if os.path.exists(json_src):
                shutil.copy2(json_src, json_dst)
            if os.path.exists(jpg_src):
                shutil.copy2(jpg_src, jpg_dst)
        else:
            if os.path.exists(json_dst):
                os.remove(json_dst)
            if os.path.exists(jpg_dst):
                os.remove(jpg_dst)

        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/map", response_class=HTMLResponse)
async def serve_map():
    with open(MAP_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two WGS-84 points."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


def _heading_delta_deg(a, b):
    """Signed shortest angular difference (a - b) wrapped to (-180, 180]."""
    if a is None or b is None:
        return None
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


@app.get("/api/stats")
async def get_stats():
    """
    Flat list of every saved pose, sorted newest-first by wall-clock time,
    with the pre-computed numbers the map.html Statistics view plots:

      - rawVsVpsDistanceM    horizontal distance raw-GNSS  <-> VPS  (metres)
      - headingDeltaDeg      magnetic-compass heading - VPS heading (signed deg)
      - appRuntimeSeconds    seconds since the Unity process started
      - vpsHorizontalAccuracy / vpsHeadingAccuracy  for cross-plotting

    Files that pre-date the new wallClockUnixMs field fall back to the
    Unix timestamp encoded in their filename (location_<unix>.json) so the
    historical pose archive still appears with a real wall-clock time.
    Files that pre-date the appRuntimeSeconds field fall back to the
    ``timestamp`` field (Unity Time.timeAsDouble at snap, seconds-since-scene-load).
    """
    rows = []
    for entry in _list_pose_files(newest_first=False):  # oldest-first for now
        path     = entry["path"]
        filename = entry["filename"]
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue

        raw   = d.get("rawGPS")      or {}
        vps   = d.get("vps")         or {}
        corrs = d.get("corrections") or {}

        raw_lat = raw.get("latitude")
        raw_lon = raw.get("longitude")
        if raw_lat in (0, 0.0): raw_lat = None
        if raw_lon in (0, 0.0): raw_lon = None
        vps_lat = vps.get("latitude")
        vps_lon = vps.get("longitude")

        raw_hdg_mag = raw.get("magneticHeading")
        if raw_hdg_mag in (None, 0, 0.0):
            raw_hdg_mag = raw.get("heading")
        vps_hdg = vps.get("heading")

        # Wall-clock fallback: parse Unix timestamp out of "location_<unix>.json".
        wall_ms = d.get("wallClockUnixMs")
        if not wall_ms:
            m = re.match(r"^location_(\d+)(?:\.json)?$", os.path.splitext(filename)[0])
            if m:
                wall_ms = int(m.group(1)) * 1000
        if not wall_ms:
            # Last resort: file mtime in ms.
            wall_ms = int(entry["mtime"] * 1000)

        # App-runtime fallback: use the legacy `timestamp` field (Time.timeAsDouble).
        runtime_s = d.get("appRuntimeSeconds")
        if runtime_s is None:
            runtime_s = d.get("timestamp")

        rows.append({
            "filename":               filename,
            "wallClockUnixMs":        wall_ms,
            "appRuntimeSeconds":      runtime_s,
            "sessionTimestamp":       d.get("timestamp"),
            "selected":               entry["selected"],

            "rawLat":                 raw_lat,
            "rawLon":                 raw_lon,
            "rawMagneticHeading":     raw_hdg_mag,
            "rawHorizontalAccuracy":  raw.get("horizontalAccuracy"),

            "vpsLat":                 vps_lat,
            "vpsLon":                 vps_lon,
            "vpsHeading":             vps_hdg,
            "vpsHorizontalAccuracy":  vps.get("horizontalAccuracy"),
            "vpsHeadingAccuracy":     vps.get("headingAccuracy"),

            "rawVsVpsDistanceM":      _haversine_m(raw_lat, raw_lon, vps_lat, vps_lon),
            "headingDeltaDeg":        _heading_delta_deg(raw_hdg_mag, vps_hdg),

            "hasHeadingFix":          corrs.get("hasHeadingFix"),
            "headingCorrectionApplied": corrs.get("headingCorrectionApplied"),
        })

    # Newest-first so the Statistics table reads top-down from latest snap.
    rows.sort(key=lambda r: r["wallClockUnixMs"] or 0, reverse=True)
    return rows


@app.get("/api/export")
async def export_poses(which: str = "all"):
    """Stream a .zip containing every (or just the selected) pose JSON plus
    its companion .jpg snapshot if one exists. ``which`` is 'all' or 'selected'."""
    if which not in ("all", "selected"):
        which = "all"

    entries = _list_pose_files(newest_first=True)
    if which == "selected":
        entries = [e for e in entries if e["selected"]]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            try:
                zf.write(e["path"], arcname=e["filename"])
            except Exception:
                continue
            if e["has_image"]:
                try:
                    zf.write(e["jpg_path"], arcname=e["jpg_name"])
                except Exception:
                    pass
        # Small manifest so the consumer can read the export without scanning.
        manifest = {
            "exported_at_unix_ms": int(time.time() * 1000),
            "which":               which,
            "file_count":          len(entries),
            "files":               [e["filename"] for e in entries],
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = f"twin2ar-poses-{which}-{ts}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

class ARPoseDef(BaseModel):
    latitude: float
    longitude: float
    altitude: float
    heading: float
    pitch: float
    roll: float
    timestamp: float

@app.post("/align")
async def align_image(
    image: UploadFile = File(...),
    pose_json: str = Form(...)
):
    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    real_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    timestamp = str(int(time.time()))
    base_name = f"location_{timestamp}"

    img_path = os.path.join(TEST_DIR, f"{base_name}.jpg")
    json_path = os.path.join(TEST_DIR, f"{base_name}.json")

    cv2.imwrite(img_path, real_image)

    with open(json_path, "w", encoding="utf-8") as f:
        f.write(pose_json)

    return {
        "status": "success",
        "message": f"Saved {base_name}.jpg and .json for local testing!"
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8050, reload=True)