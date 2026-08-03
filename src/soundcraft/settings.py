"""Schema-driven settings store backed by `.env` + environment variables.

Every persisted value is described by a :class:`SettingSpec`. Core settings live
here; provider settings come from the provider registry. Nothing in the GUI or
the HTTP layer hardcodes a key name, so a new provider brings its own settings
UI along with it.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

from soundcraft.paths import (
    app_env_path,
    default_output_dir,
    ensure_app_dirs,
    is_app_mode,
    workflows_dir,
)
from soundcraft.providers.base import SettingSpec

log = logging.getLogger(__name__)

# Serialises read-modify-write of the settings file across request threads.
_save_lock = threading.Lock()

CORE_SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec(
        key="LM_STUDIO_URL",
        label="LM Studio URL",
        default="http://localhost:1234",
        help="Optional local LLM used to refine prompts. Leave as-is if unused.",
        placeholder="http://localhost:1234",
    ),
    SettingSpec(
        key="LM_STUDIO_MODEL",
        label="LM Studio model",
        default="liquid/lfm2-24b-a2b",
        help="Model id served by LM Studio (or any OpenAI-compatible endpoint).",
        placeholder="liquid/lfm2-24b-a2b",
    ),
    SettingSpec(
        key="SOUNDCRAFT_API_TOKEN",
        label="API token",
        secret=True,
        help=(
            "When set, every HTTP request must send this as a Bearer token. "
            "Required before exposing the server beyond localhost."
        ),
    ),
    SettingSpec(
        key="SOUNDCRAFT_CORS_ORIGINS",
        label="Allowed CORS origins",
        help=(
            "Comma-separated origins allowed to call the API from a browser. "
            "Only needed when a web page on another host talks to soundcraft."
        ),
        placeholder="https://example.com",
    ),
)


def all_specs() -> tuple[SettingSpec, ...]:
    """Core settings plus every registered provider's settings, deduplicated."""
    from soundcraft.providers import registry

    specs: list[SettingSpec] = list(CORE_SETTINGS)
    seen = {s.key for s in specs}
    for provider in registry.all_providers():
        for spec in provider.settings:
            if spec.key not in seen:
                seen.add(spec.key)
                specs.append(spec)
    return tuple(specs)


def spec_for(key: str) -> SettingSpec | None:
    for spec in all_specs():
        if spec.key == key:
            return spec
    return None


# -- loading ------------------------------------------------------------------


def _candidate_env_paths() -> list[Path]:
    """App mode trusts Application Support first; dev mode trusts the project."""
    app_env = app_env_path()
    cwd_env = Path.cwd() / ".env"
    return [app_env, cwd_env] if is_app_mode() else [cwd_env, app_env]


def load(*, override: bool = False) -> None:
    """Load `.env` files so the *first* candidate path wins.

    `load_dotenv(override=True)` lets the last file read win, which is the
    opposite of the precedence `_candidate_env_paths` describes — so with
    override we read the list backwards.
    """
    paths = _candidate_env_paths()
    for path in (reversed(paths) if override else paths):
        if path.is_file():
            # No interpolation: a token containing `$` is a token, not a
            # reference to another variable.
            load_dotenv(path, override=override, interpolate=False)


# -- access -------------------------------------------------------------------


def get(key: str, default: str | None = None) -> str:
    """Read a setting.

    An explicitly-set empty value means "off" and is returned as such; only an
    absent variable falls back to the spec default. That is what makes it
    possible to clear a setting that has a non-empty default.
    """
    value = os.getenv(key)
    if value is not None:
        return value
    if default is not None:
        return default
    spec = spec_for(key)
    return spec.default if spec else ""


def get_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_set(key: str) -> bool:
    return bool(os.getenv(key, "").strip())


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "…" + value[-4:]


def read_public() -> dict[str, Any]:
    """Settings payload for the GUI/API. Secrets are reported, never returned."""
    values: dict[str, Any] = {}
    for spec in all_specs():
        raw = get(spec.key)
        if spec.secret:
            values[spec.key] = {"set": bool(raw), "masked": mask(raw)}
        else:
            values[spec.key] = {"value": raw}

    out = default_output_dir().expanduser().resolve()
    return {
        "schema": [s.as_dict() for s in all_specs()],
        "values": values,
        "output_dir": str(out),
        "workflows_dir": str(workflows_dir()),
        "env_path": str(app_env_path()),
        "app_mode": is_app_mode(),
        "auth_required": is_set("SOUNDCRAFT_API_TOKEN"),
    }


def _quote(value: str) -> str:
    """Serialise a value so `.env` round-trips it exactly."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _clean(key: str, value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if "\n" in text or "\r" in text:
        # A newline would let one setting write arbitrary extra keys.
        raise ValueError(f"{key}: a setting value cannot contain a line break")
    return text


def _write_atomically(path: Path, body: str) -> None:
    """Replace the settings file in one step, never leaving it truncated."""
    tmp = path.with_name(path.name + ".tmp")
    # Created 0600 from the start: no window where the file is world-readable.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            tmp.unlink()
        raise


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Persist updates to the per-user `.env` and to os.environ.

    Keys absent from ``updates`` keep whatever is on disk. An explicit empty
    string clears a value — the only way to remove a saved secret.

    Values that merely happen to be in the environment (an ``export`` in a
    shell profile, a CI secret) are *not* written: persisting a credential the
    user never typed here would outlive the session they meant it for.
    """
    with _save_lock:
        ensure_app_dirs()
        known = {spec.key for spec in all_specs()}
        unknown = set(updates) - known
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")

        cleaned = {key: _clean(key, value) for key, value in updates.items()}

        path = app_env_path()
        # Start from disk so keys this build does not recognise still survive.
        current: dict[str, str] = {}
        if path.is_file():
            current = {
                k: v or "" for k, v in dotenv_values(path, interpolate=False).items()
            }
        current.update(cleaned)

        body = "\n".join(f"{key}={_quote(current[key])}" for key in sorted(current))
        _write_atomically(path, body + "\n")

        # Only the keys we just wrote are pushed into the process environment;
        # unknown keys from disk are preserved on disk but never re-exported.
        for key, value in cleaned.items():
            os.environ[key] = value

    _notify_changed(cleaned.keys())
    return read_public()


def _notify_changed(keys: Iterable[str]) -> None:  # noqa: D401
    """Let providers drop cached clients built from now-stale credentials."""
    from soundcraft.providers import registry

    changed = set(keys)
    for provider in registry.all_providers():
        on_change = getattr(provider, "on_settings_changed", None)
        if on_change is None:
            continue
        if changed & {s.key for s in provider.settings}:
            try:
                on_change()
            except Exception:  # A broken provider must not block saving.
                log.warning("%s failed to reload its settings", provider.id, exc_info=True)


# Load the user's `.env` as soon as settings are imported, so every entry point
# (CLI, server, desktop app, tests) sees the same values. The desktop app calls
# config.enable_app_mode() afterwards to reload with app-mode precedence.
load(override=False)
