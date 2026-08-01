"""Local HTTP API + GUI, for browsers, TouchDesigner and anything else.

The API is generated from provider metadata: `/providers` describes every
backend, its parameters and whether it is ready, so clients never need a
hardcoded list of backends.
"""

from __future__ import annotations

import logging
import re
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

queue = JobQueue()


# -- auth ---------------------------------------------------------------------


def api_token() -> str:
    """The configured API token, if any. One definition, used everywhere."""
    return settings.get("SOUNDCRAFT_API_TOKEN").strip()


def _token_matches(presented: str) -> bool:
    # compare_digest raises TypeError on non-ASCII str, and the presented value
    # is attacker-controlled — compare bytes so a stray character is a 401, not
    # a 500.
    return secrets.compare_digest(presented.encode("utf-8"), api_token().encode("utf-8"))


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:] if header[:7].lower() == "bearer " else ""


def require_auth(request: Request) -> None:
    """Enforce the API token when one is configured."""
    if not api_token():
        return
    if not _token_matches(_bearer(request)):
        raise HTTPException(401, "Invalid or missing API token")


def require_media_auth(request: Request) -> None:
    """Same, but also accepts `?token=`.

    `<audio src>` and download links cannot set headers. Restricted to media so
    that destructive routes never put the token somewhere it can be logged.
    """
    if not api_token():
        return
    presented = _bearer(request) or request.query_params.get("token", "")
    if not _token_matches(presented):
        raise HTTPException(401, "Invalid or missing API token")


Auth = Depends(require_auth)
MediaAuth = Depends(require_media_auth)


def cors_origins() -> list[str]:
    raw = settings.get("SOUNDCRAFT_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Build the application, middleware included.

    Middleware has to be attached before the app starts, and both entry points
    (`soundcraft serve` and the desktop window) must get the same one — so it is
    wired here rather than inside a run function.
    """
    application = FastAPI(
        title="soundcraft",
        description="Local API and GUI for generating music with pluggable backends",
        version=APP_VERSION,
    )

    origins = cors_origins()
    if "*" in origins:
        raise SystemExit(
            "SOUNDCRAFT_CORS_ORIGINS does not accept '*': combined with credentials "
            "it would let any web page drive this server. List explicit origins."
        )
    if origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return application


app = create_app()


def assert_bind_is_safe(host: str) -> None:
    """Refuse to expose an unauthenticated server beyond this machine."""
    if host not in LOOPBACK_HOSTS and not api_token():
        raise SystemExit(
            f"Refusing to bind {host} without authentication.\n"
            "Set an API token first:\n"
            "  soundcraft config set SOUNDCRAFT_API_TOKEN <a-long-random-string>\n"
            "…or bind 127.0.0.1 to keep the server local."
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
    output_dir: str | None = Field(
        None, description="Output directory; must be inside a library directory"
    )


class GenerateResponse(BaseModel):
    input: str
    prompt: str
    backend: str
    params: dict[str, Any]
    files: list[str]


class RefineRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


# -- generation ---------------------------------------------------------------

#: Domain failures, and how each maps onto HTTP. Ordered: first match wins.
ERROR_CODES: tuple[tuple[type[Exception], int, str], ...] = (
    (ProviderUnavailable, 400, "backend_not_configured"),
    (ValueError, 400, "invalid_request"),
    (ProviderError, 502, "backend_failed"),
    (OSError, 500, "io_error"),
)


def classify(error: Exception) -> tuple[int, str]:
    for kind, status, code in ERROR_CODES:
        if isinstance(error, kind):
            return status, code
    return 500, "internal_error"


def as_http(error: Exception) -> HTTPException:
    status, _ = classify(error)
    return HTTPException(status, str(error) or type(error).__name__)


def _generate(req: GenerateRequest, on_progress=None) -> GenerateResponse:
    """Run a generation. Raises domain exceptions, never HTTPException.

    Called from request handlers and from job workers alike, so it must not
    bake in a transport.
    """
    backend = req.backend or registry.default_id()
    if not backend:
        raise ProviderUnavailable("No generation backends are registered.")
    if not registry.has(backend):
        # A bad id is the caller's mistake, not an upstream failure — check it
        # here so it maps to 400 rather than 502.
        raise ValueError(
            f"Unknown backend {backend!r}. Available: {', '.join(registry.ids())}"
        )

    provider = registry.get(backend)
    status = provider.availability()
    if not status.ready:
        raise ProviderUnavailable(f"{status.reason} {status.fix}".strip())

    if req.output_dir:
        output_dir = Path(req.output_dir).expanduser().resolve()
        if not is_in_library(output_dir):
            raise ValueError(
                "output_dir must be inside a library directory "
                f"({', '.join(str(r) for r in library_roots())}). "
                "Use the CLI's -o flag to write elsewhere."
            )
    else:
        output_dir = default_output_dir()

    result = run_generate(
        req.prompt,
        backend=backend,
        params=req.params,
        count=req.count,
        output_dir=output_dir,
        raw=req.raw,
        progress=on_progress,
    )
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
        "auth_required": bool(api_token()),
    }


@app.get("/providers", dependencies=[Auth])
def get_providers() -> dict[str, Any]:
    """Every backend with its parameters and readiness — drives the whole UI."""
    return {**registry.snapshot(), "refiner_available": refiner_available()}


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
    try:
        return _generate(req)
    except Exception as e:
        raise as_http(e) from e


@app.post("/jobs", status_code=202, dependencies=[Auth])
def create_job(req: GenerateRequest) -> dict[str, Any]:
    """Asynchronous generation. Returns immediately; poll `GET /jobs/{id}`."""
    def work(job) -> dict[str, Any]:
        def on_progress(done: int, total: int, _path: Path) -> None:
            queue.set_progress(job.id, done, total)

        return _generate(req, on_progress).model_dump()

    job = queue.submit(req.model_dump(), work, classify=classify)
    return job.as_dict()


@app.get("/jobs", dependencies=[Auth])
def list_jobs(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    jobs = queue.recent(limit)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/jobs/{job_id}", dependencies=[Auth])
def get_job(job_id: str) -> dict[str, Any]:
    job = queue.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    return job


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


@app.get("/media", dependencies=[MediaAuth])
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


TOKEN_IN_URL = re.compile(r"([?&]token=)[^&\s]+")


def redact_token(text: str) -> str:
    return TOKEN_IN_URL.sub(r"\1<redacted>", text)


def install_access_log_redaction() -> None:
    """Keep `?token=` out of uvicorn's access log.

    `/media` accepts the token as a query parameter because `<audio src>` cannot
    send a header, and uvicorn logs the full request line.
    """
    from uvicorn.logging import AccessFormatter

    if getattr(AccessFormatter, "_soundcraft_redacts", False):
        return

    original = AccessFormatter.formatMessage

    def formatMessage(self, record):  # noqa: N802 - logging's own naming
        return redact_token(original(self, record))

    AccessFormatter.formatMessage = formatMessage
    AccessFormatter._soundcraft_redacts = True


def run_server(
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    *,
    open_browser: bool = False,
) -> None:
    import uvicorn

    assert_bind_is_safe(host)
    install_access_log_redaction()

    url = f"http://{host}:{port}"
    print(f"soundcraft {APP_VERSION} listening on {url}")
    print(f"  GUI            {url}/")
    print(f"  Backends       {', '.join(registry.ids())}")
    if api_token():
        print("  Auth           Bearer token required")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
