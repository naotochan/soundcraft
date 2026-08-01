"""Application constants and settings bootstrap.

Paths live in :mod:`soundcraft.paths`, persisted values in
:mod:`soundcraft.settings`, and backend definitions in
:mod:`soundcraft.providers`. This module holds what is left: constants and the
import-time load of the user's `.env`.
"""

from __future__ import annotations

from soundcraft import settings
from soundcraft.paths import (  # re-exported for convenience
    APP_NAME,
    app_env_path,
    app_support_dir,
    default_output_dir,
    documents_dir,
    ensure_app_dirs,
    is_app_mode,
    workflows_dir,
)
from soundcraft.paths import (
    enable_app_mode as _enable_app_mode,
)

APP_VERSION = "0.7.0"

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8765
DEFAULT_COUNT = 1

#: Hosts that are safe to bind without an API token.
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def enable_app_mode() -> None:
    """Switch to desktop-app paths and reload settings from Application Support."""
    _enable_app_mode()
    settings.load(override=True)


# Load `.env` for CLI and server entry points. The desktop app calls
# enable_app_mode() first, which reloads with app-mode precedence.
settings.load(override=False)

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "DEFAULT_COUNT",
    "DEFAULT_SERVER_HOST",
    "DEFAULT_SERVER_PORT",
    "LOOPBACK_HOSTS",
    "app_env_path",
    "app_support_dir",
    "default_output_dir",
    "documents_dir",
    "enable_app_mode",
    "ensure_app_dirs",
    "is_app_mode",
    "workflows_dir",
]
