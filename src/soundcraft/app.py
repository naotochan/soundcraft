"""Desktop app entry: embedded API server plus a native window.

pywebview is an optional dependency — a headless server install should not need
a GUI toolkit — so the import happens here, with an actionable message when it
is missing.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

from soundcraft.config import (
    APP_VERSION,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    enable_app_mode,
)

WINDOW_BACKGROUND = "#07090d"  # Matches the GUI's dark ground, so no white flash.


def _free_port(host: str, preferred: int) -> int:
    """Return the preferred port, or an OS-assigned one if it is taken.

    Two copies of the app on one machine should both open rather than the
    second dying on "address already in use".
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"The local server did not start on {host}:{port}")


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
    """Start the local API and open a native window (no external browser)."""
    try:
        import webview
    except ImportError as e:
        raise SystemExit(
            "The desktop window needs pywebview, which is not installed.\n"
            '  uv pip install -e ".[app]"\n'
            "Or run the browser GUI instead: soundcraft gui"
        ) from e

    enable_app_mode()
    port = _free_port(host, port)

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

    webview.create_window(
        f"soundcraft {APP_VERSION}",
        f"http://{host}:{port}/",
        width=1180,
        height=860,
        min_size=(880, 620),
        background_color=WINDOW_BACKGROUND,
    )
    webview.start()
    # The window closed: the process exits and the daemon server dies with it.


def main() -> None:
    run_desktop_app()


if __name__ == "__main__":
    main()
