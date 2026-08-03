"""Desktop app entry: embedded API server plus a native window.

pywebview is an optional dependency — a headless server install should not need
a GUI toolkit — so the import happens here, with an actionable message when it
is missing.
"""

from __future__ import annotations

import os
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
from soundcraft.server import assert_bind_is_safe

WINDOW_BACKGROUND = "#07090d"  # Matches the GUI's dark ground, so no white flash.


#: Wildcard binds are not addresses you can connect to; the window uses loopback.
WILDCARD_HOSTS = {"0.0.0.0": "127.0.0.1", "::": "::1", "": "127.0.0.1"}


def _connect_host(host: str) -> str:
    """A host the window and the readiness probe can actually connect to."""
    return WILDCARD_HOSTS.get(host, host)


def _url_host(host: str) -> str:
    connect = _connect_host(host)
    return f"[{connect}]" if ":" in connect else connect


def _bind_listener(host: str, preferred: int) -> socket.socket:
    """Bind a listening socket, falling back to any free port.

    The socket is handed straight to uvicorn rather than probed and closed:
    probing leaves a window for another process to take the port, and on
    Windows a probe can succeed against a port that is already in use.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET

    for port in (preferred, 0):
        listener = socket.socket(family, socket.SOCK_STREAM)
        try:
            listener.bind((host, port))
        except OSError:
            listener.close()
            continue
        listener.listen(128)
        listener.set_inheritable(True)
        return listener

    raise SystemExit(f"Could not bind any port on {host}.")


def _wait_until_serving(host: str, port: int, thread: threading.Thread) -> None:
    """Block until the server answers, or fail fast if its thread died."""
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if not thread.is_alive():
            raise SystemExit("The local server stopped before it finished starting.")
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise SystemExit(f"The local server did not start on {host}:{port}.")


def _start_server(listener: socket.socket) -> None:
    import uvicorn

    from soundcraft.server import app

    config = uvicorn.Config(app, log_level="warning")
    uvicorn.Server(config).run(sockets=[listener])


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
    # The desktop window is another way to start the same server, so it has to
    # honour the same rule about not exposing it unauthenticated.
    assert_bind_is_safe(host)

    listener = _bind_listener(host, port)
    port = listener.getsockname()[1]

    thread = threading.Thread(
        target=_start_server,
        args=(listener,),
        daemon=True,
        name="soundcraft-uvicorn",
    )
    thread.start()
    _wait_until_serving(_connect_host(host), port, thread)

    if on_started:
        on_started()

    if os.environ.get("SOUNDCRAFT_SMOKE_TEST") == "1":
        # A frozen bundle's biggest failure mode is a missing hidden import that
        # only shows up once PyInstaller has packed it — dev installs never hit
        # it because everything is importable from source. Getting this far
        # proves webview, uvicorn and the providers all loaded and the embedded
        # server actually answers, without needing a display to open a window on.
        return

    webview.create_window(
        f"soundcraft {APP_VERSION}",
        f"http://{_url_host(host)}:{port}/",
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
