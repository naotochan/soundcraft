"""Local HTTP API + GUI, for browsers, TouchDesigner and anything else.

The API is generated from provider metadata: `/providers` describes every
backend, its parameters and whether it is ready, so clients never need a
hardcoded list of backends.
"""

from __future__ import annotations

import logging
import secrets
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from soundcraft import settings
from soundcraft.config import (
    APP_VERSION,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    LOOPBACK_HOSTS,
    default_output_dir,
    workflows_dir,
)
from soundcraft.jobs import JobQueue
from soundcraft.library import (
    delete_track,
    is_in_library,
    library_roots,
    list_tracks,
    media_type_for,
)
from soundcraft.pipeline import run_generate
from soundcraft.prompt import refine_prompt, refiner_available
from soundcraft.providers import registry
from soundcraft.providers.base import ProviderError, ProviderUnavailable

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="soundcraft",
    description="Local API and GUI for generating music with pluggable backends",
    version=APP_VERSION,
)

queue = JobQueue()


# -- auth ---------------------------------------------------------------------


def require_auth(request: Request) -> None:
    """Enforce the API token when one is configured.

    Without a token the server is only safe on loopback; `run_server` refuses to
    bind a public interface unless a token is set.
    """
    expected = settings.get("SOUNDCRAFT_API_TOKEN")
    if not expected:
        return

    header = request.headers.get("authorization", "")
    presented = header[7:] if header.lower().startswith("bearer ") else ""
    if not presented:
        presented = request.query_params.get("token", "")
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(401, "Invalid or missing API token")


Auth = Depends(require_auth)


def _configure_cors() -> None:
    origins = [o.strip() for o in settings.get("SOUNDCRAFT_CORS_ORIGINS", "").split(",")]
    origins = [o for o in origins if o]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


# -- schemas ------------------------------------------------------------------


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Text prompt or keywords")
    backend: str | None = Field(
        None, description="Provider id; defaults to the first configured backend"
    )
    params: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific parameters"
    )
    count: int = Field(1, ge=1, le=10, description="Number of variations")
    raw: bool = Field(False, description="Skip LLM prompt refinement")
    output_dir: str | None = Field(None, description="Override the output directory")


class GenerateResponse(BaseModel):
    input: str
    prompt: str
    backend: str
    params: dict[str, Any]
    files: list[str]


class RefineRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


# -- generation ---------------------------------------------------------------


def _run(req: GenerateRequest, on_progress=None) -> GenerateResponse:
    backend = req.backend or registry.default_id()
    if not backend:
        raise HTTPException(503, "No generation backends are registered.")

    try:
        provider = registry.get(backend)
    except ProviderError as e:
        raise HTTPException(400, str(e)) from e

    status = provider.availability()
    if not status.ready:
        raise HTTPException(400, f"{status.reason} {status.fix}".strip())

    output_dir = Path(req.output_dir).expanduser() if req.output_dir else default_output_dir()

    try:
        result = run_generate(
            req.prompt,
            backend=backend,
            params=req.params,
            count=req.count,
            output_dir=output_dir,
            raw=req.raw,
            progress=on_progress,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except ProviderUnavailable as e:
        raise HTTPException(400, str(e)) from e
    except ProviderError as e:
        raise HTTPException(502, str(e)) from e
    except OSError as e:
        raise HTTPException(500, f"Could not write the output file: {e}") from e

    return GenerateResponse(
        input=result.input,
        prompt=result.prompt,
        backend=result.backend,
        params=result.params,
        files=[str(p) for p in result.files],
    )


# -- routes -------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    """Unauthenticated liveness probe, for container orchestration."""
    return {
        "status": "ok",
        "service": "soundcraft",
        "version": APP_VERSION,
        "auth_required": settings.is_set("SOUNDCRAFT_API_TOKEN"),
    }


@app.get("/providers", dependencies=[Auth])
def get_providers() -> dict[str, Any]:
    """Every backend with its parameters and readiness — drives the whole UI."""
    return {
        "providers": registry.describe_all(),
        "default": registry.default_id(),
        "refiner_available": refiner_available(),
    }


@app.get("/settings", dependencies=[Auth])
def get_settings() -> dict[str, Any]:
    return settings.read_public()


@app.put("/settings", dependencies=[Auth])
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Update settings by key. Omitted keys keep their value; "" clears one."""
    try:
        return settings.save(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except OSError as e:
        raise HTTPException(500, f"Could not save settings: {e}") from e


@app.post("/settings/open-output", dependencies=[Auth])
def open_output_folder() -> dict[str, str]:
    """Reveal the output directory in the desktop file manager."""
    path = default_output_dir().expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    opener = {"darwin": "open", "win32": "explorer"}.get(sys.platform, "xdg-open")
    try:
        subprocess.run([opener, str(path)], check=False)
    except OSError as e:
        raise HTTPException(500, f"Could not open the folder: {e}") from e
    return {"output_dir": str(path)}


@app.post("/refine", dependencies=[Auth])
def refine(body: RefineRequest) -> dict[str, Any]:
    """Preview what the LLM makes of a prompt without generating audio."""
    refined = refine_prompt(body.prompt)
    return {
        "input": body.prompt,
        "prompt": refined,
        "changed": refined != body.prompt,
        "available": refiner_available(),
    }


@app.post("/generate", response_model=GenerateResponse, dependencies=[Auth])
def generate(req: GenerateRequest) -> GenerateResponse:
    """Synchronous generation. Blocks until every file is written."""
    return _run(req)


@app.post("/jobs", status_code=202, dependencies=[Auth])
def create_job(req: GenerateRequest) -> dict[str, Any]:
    """Asynchronous generation. Returns immediately; poll `GET /jobs/{id}`."""
    def work(job) -> dict[str, Any]:
        def on_progress(done: int, total: int, _path: Path) -> None:
            queue.set_progress(job.id, done, total)

        return _run(req, on_progress).model_dump()

    job = queue.submit(req.model_dump(), work)
    return job.as_dict()


@app.get("/jobs", dependencies=[Auth])
def list_jobs(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    jobs = queue.list(limit)
    return {"jobs": [j.as_dict() for j in jobs], "count": len(jobs)}


@app.get("/jobs/{job_id}", dependencies=[Auth])
def get_job(job_id: str) -> dict[str, Any]:
    job = queue.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    return job.as_dict()


@app.get("/library", dependencies=[Auth])
def get_library(
    limit: int = Query(200, ge=1, le=1000),
    backend: str | None = Query(None),
) -> dict[str, Any]:
    """Generated tracks on disk, newest first, with their sidecar metadata."""
    tracks = list_tracks(limit=limit, backend=backend)
    return {
        "tracks": tracks,
        "count": len(tracks),
        "roots": [str(r) for r in library_roots()],
    }


@app.delete("/library", dependencies=[Auth])
def remove_track(path: str = Query(..., min_length=1)) -> dict[str, str]:
    try:
        delete_track(Path(path))
    except ValueError as e:
        raise HTTPException(403, str(e)) from e
    except OSError as e:
        raise HTTPException(500, f"Could not delete the file: {e}") from e
    return {"deleted": path}


@app.get("/media", dependencies=[Auth])
def media(
    path: str = Query(..., min_length=1),
    download: bool = Query(False, description="Send as an attachment instead of inline"),
) -> FileResponse:
    """Stream a generated file. Restricted to the library directories.

    Served inline by default: an `attachment` disposition makes Chrome stall a
    `<audio>` load instead of playing it.
    """
    target = Path(path).expanduser().resolve()
    if not is_in_library(target):
        raise HTTPException(403, "Path is outside the library directories")
    if not target.is_file():
        raise HTTPException(404, f"File not found: {target}")

    disposition = "attachment" if download else "inline"
    return FileResponse(
        target,
        media_type=media_type_for(target),
        headers={"Content-Disposition": f'{disposition}; filename="{target.name}"'},
    )


@app.get("/workflows", dependencies=[Auth])
def get_workflows() -> dict[str, Any]:
    """ComfyUI workflows available on this machine."""
    directory = workflows_dir()
    files = sorted(p.name for p in directory.glob("*.json")) if directory.is_dir() else []
    return {"dir": str(directory), "workflows": files}


@app.get("/")
def gui_index() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, "GUI assets are not bundled in this build")
    return FileResponse(index)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# -- entry point --------------------------------------------------------------


def run_server(
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    *,
    open_browser: bool = False,
) -> None:
    import uvicorn

    if host not in LOOPBACK_HOSTS and not settings.is_set("SOUNDCRAFT_API_TOKEN"):
        raise SystemExit(
            f"Refusing to bind {host} without authentication.\n"
            "Set an API token first:\n"
            "  soundcraft config set SOUNDCRAFT_API_TOKEN <a-long-random-string>\n"
            "…or bind 127.0.0.1 to keep the server local."
        )

    _configure_cors()

    url = f"http://{host}:{port}"
    print(f"soundcraft {APP_VERSION} listening on {url}")
    print(f"  GUI            {url}/")
    print(f"  Backends       {', '.join(registry.ids())}")
    if settings.is_set("SOUNDCRAFT_API_TOKEN"):
        print("  Auth           Bearer token required")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
