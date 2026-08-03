"""Filesystem locations. Kept dependency-free so every module can import it."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "soundcraft"


def is_app_mode() -> bool:
    """True when running as a desktop app / frozen bundle."""
    return bool(getattr(sys, "frozen", False)) or os.getenv("SOUNDCRAFT_APP") == "1"


def app_support_dir() -> Path:
    """Per-user config directory, following each platform's convention."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    base = os.getenv("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / APP_NAME


def app_env_path() -> Path:
    return app_support_dir() / ".env"


def documents_dir() -> Path:
    return Path.home() / "Documents"


def default_output_dir() -> Path:
    """Where generated audio lands.

    Overridable via SOUNDCRAFT_OUTPUT_DIR so containers and servers can point
    at a mounted volume without patching code.
    """
    override = os.getenv("SOUNDCRAFT_OUTPUT_DIR")
    if override:
        return Path(override).expanduser()
    if is_app_mode():
        return documents_dir() / APP_NAME / "output"
    return Path("output")


def workflows_dir() -> Path:
    """User-supplied ComfyUI workflows."""
    return app_support_dir() / "workflows"


def ensure_app_dirs() -> None:
    app_support_dir().mkdir(parents=True, exist_ok=True)
    workflows_dir().mkdir(parents=True, exist_ok=True)
    default_output_dir().mkdir(parents=True, exist_ok=True)


def enable_app_mode() -> None:
    """Mark the process as a desktop app and materialise its directories."""
    os.environ["SOUNDCRAFT_APP"] = "1"
    ensure_app_dirs()
