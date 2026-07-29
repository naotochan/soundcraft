"""Local HTTP API + GUI for external tools (TouchDesigner, browser, etc.)."""

from __future__ import annotations

import threading
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from soundcraft.config import (
    BACKENDS,
    DEFAULT_BACKEND,
    DEFAULT_DURATION,
    DEFAULT_MODEL,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    MODELS,
    default_output_dir,
    get_gemini_api_key,
    get_replicate_api_token,
    read_settings_public,
    save_settings,
)
from soundcraft.library import library_roots, list_tracks
from soundcraft.pipeline import run_generate

STATIC_DIR = Path(__file__).resolve().parent / "static"
APP_VERSION = "0.6.0"

app = FastAPI(
    title="soundcraft",
    description="Local API and GUI for instrumental music generation (MusicGen / Lyria3)",
    version=APP_VERSION,
)

_jobs_lock = threading.Lock()
_jobs: dict[str, Job] = {}


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


@dataclass
class Job:
    id: str
    status: JobStatus
    created_at: str
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    updated_at: str = field(default="")


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Text prompt or keywords")
    backend: str = Field(DEFAULT_BACKEND, description="musicgen or lyria3")
    model: str = Field(DEFAULT_MODEL, description="MusicGen model version")
    duration: int = Field(DEFAULT_DURATION, ge=1, le=120)
    count: int = Field(1, ge=1, le=10)
    raw: bool = Field(False, description="Skip LLM prompt refinement")
    output_dir: str | None = Field(None, description="Output directory (default: output/)")


class GenerateResponse(BaseModel):
    input: str
    prompt: str
    backend: str
    files: list[str]


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: str
    updated_at: str
    request: dict[str, Any]
    result: GenerateResponse | None = None
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_request(req: GenerateRequest) -> None:
    if req.backend not in BACKENDS:
        raise HTTPException(400, f"Invalid backend. Choose from: {BACKENDS}")
    if req.backend == "musicgen" and req.model not in MODELS:
        raise HTTPException(400, f"Invalid model. Choose from: {MODELS}")


def _allowed_media_roots() -> list[Path]:
    return library_roots()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _run_sync(req: GenerateRequest) -> GenerateResponse:
    _validate_request(req)
    if req.backend == "musicgen" and not get_replicate_api_token():
        raise HTTPException(
            400,
            "REPLICATE_API_TOKEN is not set. Open Settings and add your Replicate token.",
        )
    if req.backend == "lyria3" and not get_gemini_api_key():
        raise HTTPException(
            400,
            "GEMINI_API_KEY is not set. Open Settings and add your Gemini API key.",
        )
    output_dir = Path(req.output_dir) if req.output_dir else default_output_dir()
    try:
        result = run_generate(
            req.prompt,
            backend=req.backend,
            model=req.model,
            duration=req.duration,
            count=req.count,
            output_dir=output_dir,
            raw=req.raw,
        )
    except SystemExit as e:
        raise HTTPException(500, str(e) or "Generation failed") from e
    except Exception as e:
        raise HTTPException(500, str(e)) from e

    return GenerateResponse(
        input=result.input,
        prompt=result.prompt,
        backend=result.backend,
        files=[str(p) for p in result.files],
    )


def _execute_job(job_id: str, req: GenerateRequest) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = JobStatus.running
        job.updated_at = _now()

    try:
        response = _run_sync(req)
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = JobStatus.succeeded
            job.result = response.model_dump()
            job.updated_at = _now()
    except HTTPException as e:
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = JobStatus.failed
            job.error = e.detail if isinstance(e.detail, str) else str(e.detail)
            job.updated_at = _now()
    except Exception as e:
        with _jobs_lock:
            job = _jobs[job_id]
            job.status = JobStatus.failed
            job.error = str(e)
            job.updated_at = _now()


def _job_to_response(job: Job) -> JobResponse:
    result = None
    if job.result is not None:
        result = GenerateResponse(**job.result)
    return JobResponse(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at or job.created_at,
        request=job.request,
        result=result,
        error=job.error,
    )


class SettingsUpdate(BaseModel):
    replicate_api_token: str | None = Field(
        None, description="New Replicate token; omit to keep, empty string to clear"
    )
    gemini_api_key: str | None = Field(
        None, description="New Gemini key; omit to keep, empty string to clear"
    )
    lm_studio_url: str | None = None
    lm_studio_model: str | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "soundcraft", "version": APP_VERSION}


@app.get("/settings")
def get_settings() -> dict:
    return read_settings_public()


@app.put("/settings")
def put_settings(body: SettingsUpdate) -> dict:
    return save_settings(
        replicate_api_token=body.replicate_api_token,
        gemini_api_key=body.gemini_api_key,
        lm_studio_url=body.lm_studio_url,
        lm_studio_model=body.lm_studio_model,
    )


@app.post("/settings/open-output")
def open_output_folder() -> dict[str, str]:
    """Reveal the output directory in Finder (macOS) / file manager."""
    import subprocess
    import sys

    path = default_output_dir().expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError as e:
        raise HTTPException(500, f"Could not open folder: {e}") from e
    return {"output_dir": str(path)}


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    """Synchronous generation. Blocks until files are written (can take minutes)."""
    return _run_sync(req)


@app.post("/jobs", response_model=JobResponse, status_code=202)
def create_job(req: GenerateRequest) -> JobResponse:
    """Async generation. Returns immediately; poll GET /jobs/{id}."""
    _validate_request(req)
    job_id = uuid.uuid4().hex[:12]
    now = _now()
    job = Job(
        id=job_id,
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
        request=req.model_dump(),
    )
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(target=_execute_job, args=(job_id, req), daemon=True)
    thread.start()
    return _job_to_response(job)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"Job not found: {job_id}")
        return _job_to_response(job)


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs() -> list[JobResponse]:
    with _jobs_lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [_job_to_response(j) for j in jobs]


@app.get("/library")
def get_library(limit: int = Query(200, ge=1, le=1000)) -> dict:
    """List generated tracks on disk (newest first), with optional sidecar meta."""
    tracks = list_tracks(limit=limit)
    return {
        "tracks": tracks,
        "count": len(tracks),
        "roots": [str(r) for r in library_roots()],
    }


@app.get("/media")
def media(path: str = Query(..., min_length=1)) -> FileResponse:
    """Serve a generated audio file for in-browser playback (output/ only)."""
    target = Path(path).expanduser().resolve()
    if not any(_is_under(target, root) for root in _allowed_media_roots()):
        raise HTTPException(403, "Path is outside allowed output directories")
    if not target.is_file():
        raise HTTPException(404, f"File not found: {target}")
    suffix = target.suffix.lower()
    media_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    return FileResponse(target, media_type=media_type, filename=target.name)


@app.get("/")
def gui_index() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "GUI assets not found")
    return FileResponse(index)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def run_server(
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    *,
    open_browser: bool = False,
) -> None:
    import uvicorn

    url = f"http://{host}:{port}"
    print(f"soundcraft listening on {url}")
    print("  GUI  /")
    print("  GET  /health")
    print("  POST /generate   (sync)")
    print("  POST /jobs       (async)")
    print("  GET  /jobs/{id}")
    print("  GET  /library")
    print("  GET  /media?path=")
    print("  GET  /settings")
    print("  PUT  /settings")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
