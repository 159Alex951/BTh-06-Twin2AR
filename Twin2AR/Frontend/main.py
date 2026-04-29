from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import cv2
import numpy as np
import os
import glob
import time
import shutil

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
    files = glob.glob(os.path.join(TEST_DIR, "*.json"))
    files.sort(key=os.path.getmtime, reverse=True)

    locations = []
    for f in files:
        filename = os.path.basename(f)
        jpg_name = filename[:-5] + ".jpg"
        locations.append({
            "filename": filename,
            "selected": os.path.exists(os.path.join(SELECT_DIR, filename)),
            "has_image": os.path.exists(os.path.join(TEST_DIR, jpg_name))
        })

    return locations

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