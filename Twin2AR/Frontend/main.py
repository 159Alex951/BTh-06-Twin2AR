from fastapi import FastAPI, File, UploadFile, Form
from fastapi import FastAPI, File, UploadFile, Form
import uvicorn
import cv2
import numpy as np
from pydantic import BaseModel
import json
import align_a
import align_b
import align_c

app = FastAPI()
# for testing health endpoint, can be removed later
@app.get("/health")
async def health():
    return {"status": "ok"}

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
    # Parse the image ONCE here to prevent async confusion downstream
    contents = await image.read()
    nparr = np.frombuffer(contents, np.uint8)
    real_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # Here you can toggle which algorithm to test: A, B, or C
    using_algorithm = "B"

    if using_algorithm == "A":
        correction = align_a.align_wireframe(real_image, pose_json)
    elif using_algorithm == "B":
        correction = align_b.align_render(real_image, pose_json)
    elif using_algorithm == "C":
        correction = align_c.align_hybrid(real_image, pose_json)

    return correction

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8050)
