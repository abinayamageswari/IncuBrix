
import sys
import uuid
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# Project folders
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
CLIP_DIR = BASE_DIR / "clips"
STATIC_DIR = BASE_DIR / "static"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCRIPT_FILE = UPLOAD_DIR / "current_script.txt"
RATIO_FILE = UPLOAD_DIR / "current_aspect_ratio.txt"
AUDIO_FILE = UPLOAD_DIR / "narration.wav"

AUDIO_GENERATOR = BASE_DIR / "generate_audio.py"
VIDEO_RENDERER = BASE_DIR / "render_video.py"


# Create FastAPI application
app = FastAPI(
    title="IncuBrix B-roll Video Engine",
    description="Generate narrated videos with captions and different aspect ratios.",
    version="1.0.0"
)

# Serve the frontend
if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static"
    )

# Store jobs while the server is running
jobs = {}


class VideoRequest(BaseModel):
    script: str = Field(..., min_length=1)
    audio_url: str = ""
    aspect_ratios: list[str] = Field(default=["16:9"])
    style: str = "nature"
    captions: bool = True


def get_output_path(ratio: str) -> Path:
    filename = f"final_video_{ratio.replace(':', 'x')}.mp4"
    return OUTPUT_DIR / filename


def process_job(job_id: str, request_data: dict):
    ratio = request_data["aspect_ratios"][0]

    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["message"] = "Generating narration..."

        # Save the script and selected aspect ratio
        SCRIPT_FILE.write_text(
            request_data["script"],
            encoding="utf-8"
        )

        RATIO_FILE.write_text(
            ratio,
            encoding="utf-8"
        )

        # Generate narration audio
        audio_result = subprocess.run(
            [
                sys.executable,
                str(AUDIO_GENERATOR),
                request_data["script"]
            ],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=300
        )

        if audio_result.returncode != 0:
            raise RuntimeError(
                audio_result.stderr
                or audio_result.stdout
                or "Audio generation failed."
            )

        if not AUDIO_FILE.exists():
            raise FileNotFoundError(
                f"Narration file was not created: {AUDIO_FILE}"
            )

        jobs[job_id]["message"] = "Rendering video..."

        # Determine output path before rendering
        output_file = get_output_path(ratio)

        # Render video with all required arguments
        video_result = subprocess.run(
            [
                sys.executable,
                str(VIDEO_RENDERER),
                str(AUDIO_FILE),
                str(output_file),
                ratio
            ],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=600
        )

        if video_result.returncode != 0:
            raise RuntimeError(
                video_result.stderr
                or video_result.stdout
                or "Video rendering failed."
            )

        if not output_file.exists() or output_file.stat().st_size == 0:
            raise FileNotFoundError(
                f"Expected video was not created correctly: {output_file}"
            )

        # Mark job as successful
        jobs[job_id]["status"] = "succeeded"
        jobs[job_id]["message"] = "Video created successfully."
        jobs[job_id]["output_file"] = str(output_file)
        jobs[job_id]["output_url"] = (
            f"/api/v1/broll/jobs/{job_id}/download"
        )
        jobs[job_id]["completed_at"] = (
            datetime.now(timezone.utc).isoformat()
        )

    except Exception as error:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["message"] = str(error)
        jobs[job_id]["output_file"] = None
        jobs[job_id]["output_url"] = None


# Homepage
@app.get("/")
def home():
    index_file = STATIC_DIR / "index.html"

    if not index_file.exists():
        raise HTTPException(
            status_code=500,
            detail="static/index.html was not found."
        )

    return FileResponse(str(index_file))


# Create a video generation job
@app.post("/api/v1/broll/jobs", status_code=202)
def create_video_job(
    request: VideoRequest,
    background_tasks: BackgroundTasks
):
    script = request.script.strip()

    if not script:
        raise HTTPException(
            status_code=400,
            detail="Script cannot be empty."
        )

    if not request.aspect_ratios:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one aspect ratio."
        )

    ratio = request.aspect_ratios[0]
    allowed_ratios = ["16:9", "9:16", "1:1"]

    if ratio not in allowed_ratios:
        raise HTTPException(
            status_code=400,
            detail="Aspect ratio must be 16:9, 9:16, or 1:1."
        )

    if not AUDIO_GENERATOR.exists():
        raise HTTPException(
            status_code=500,
            detail="generate_audio.py was not found."
        )

    if not VIDEO_RENDERER.exists():
        raise HTTPException(
            status_code=500,
            detail="render_video.py was not found."
        )

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "message": "Video generation job created.",
        "aspect_ratio": ratio,
        "output_file": None,
        "output_url": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    request_data = request.model_dump()
    request_data["script"] = script

    background_tasks.add_task(
        process_job,
        job_id,
        request_data
    )

    return jobs[job_id]


# List all jobs
@app.get("/api/v1/broll/jobs")
def list_video_jobs():
    return {"jobs": list(jobs.values())}


# Get job status
@app.get("/api/v1/broll/jobs/{job_id}")
def get_video_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job ID not found."
        )

    return jobs[job_id]


# Preview generated video
@app.get("/api/v1/broll/jobs/{job_id}/preview")
def preview_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job ID not found."
        )

    job = jobs[job_id]

    if job["status"] != "succeeded" or not job["output_file"]:
        raise HTTPException(
            status_code=409,
            detail="Video is not ready for preview."
        )

    output_file = Path(job["output_file"])

    if not output_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Generated video file was not found."
        )

    return FileResponse(
        path=str(output_file),
        media_type="video/mp4"
    )


# Download generated video
@app.get("/api/v1/broll/jobs/{job_id}/download")
def download_video(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job ID not found."
        )

    job = jobs[job_id]

    if job["status"] != "succeeded" or not job["output_file"]:
        raise HTTPException(
            status_code=409,
            detail="Video is not ready for download."
        )

    output_file = Path(job["output_file"])

    if not output_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Generated video file was not found."
        )

    return FileResponse(
        path=str(output_file),
        media_type="video/mp4",
        filename=output_file.name
    )
