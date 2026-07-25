"""Desktop app entry: embedded FastAPI + pywebview window."""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable

from soundcraft.config import (
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    enable_app_mode,
)


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Server did not start on {host}:{port}")


def _start_server(host: str, port: int) -> None:
    import uvicorn

    from soundcraft.server import app

    uvicorn.run(app, host=host, port=port, log_level="warning")


def run_desktop_app(
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
    *,
    on_started: Callable[[], None] | None = None,
) -> None:
    """Start local API and open a native window (no external browser)."""
    enable_app_mode()

    thread = threading.Thread(
        target=_start_server,
        args=(host, port),
        daemon=True,
        name="soundcraft-uvicorn",
    )
    thread.start()
    _wait_for_port(host, port)

    if on_started:
        on_started()

    import webview

    url = f"http://{host}:{port}/"
    window = webview.create_window(
        "soundcraft",
        url,
        width=1100,
        height=820,
        min_size=(720, 560),
        background_color="#12141a",
    )
    webview.start()
    # Window closed — process exits; daemon server thread dies with it.
    _ = window


def main() -> None:
    run_desktop_app()


if __name__ == "__main__":
    main()
