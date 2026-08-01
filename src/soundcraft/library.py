"""Disk-backed generation library (Suno/Udio-style history).

The audio files on disk are the source of truth; a JSON sidecar next to each one
carries the prompt and settings it was made with. Delete the audio and the
history entry goes with it — nothing to keep in sync.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soundcraft.paths import APP_NAME, default_output_dir, documents_dir

AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus", ".aiff"}
MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".opus": "audio/opus",
    ".aiff": "audio/aiff",
}
META_VERSION = 2


def media_type_for(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def library_roots() -> list[Path]:
    """Directories that may contain generated audio, most relevant first."""
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    add(default_output_dir())
    add(Path.cwd() / "output")
    add(documents_dir() / APP_NAME / "output")
    return roots


def meta_path_for(audio: Path) -> Path:
    return audio.with_suffix(".json")


def write_track_meta(
    audio: Path,
    *,
    input_text: str,
    prompt: str,
    backend: str,
    params: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write the sidecar JSON that makes a file reproducible."""
    payload: dict[str, Any] = {
        "version": META_VERSION,
        "input": input_text,
        "prompt": prompt,
        "backend": backend,
        "params": _jsonable(params or {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file": audio.name,
    }
    if extra:
        payload["extra"] = _jsonable(extra)

    path = meta_path_for(audio)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    """Drop anything that would make the sidecar unwritable."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            clean[key] = value
        else:
            clean[key] = str(value)
    return clean


def _read_meta(audio: Path) -> dict[str, Any]:
    path = meta_path_for(audio)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _title_from_name(name: str) -> str:
    stem = Path(name).stem
    head, _, tail = stem.rpartition("_")
    if head and tail.isdigit():
        stem = head
    return stem.replace("_", " ").strip() or name


def _mtime_iso(path: Path) -> str:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def track_from_file(audio: Path) -> dict[str, Any]:
    meta = _read_meta(audio)
    try:
        size = audio.stat().st_size
    except OSError:
        size = 0

    prompt = str(meta.get("prompt") or "")
    input_text = str(meta.get("input") or "")
    params = meta.get("params") if isinstance(meta.get("params"), dict) else {}

    return {
        "id": str(audio),
        "path": str(audio),
        "name": audio.name,
        "title": prompt or input_text or _title_from_name(audio.name),
        "input": input_text,
        "prompt": prompt,
        "backend": str(meta.get("backend") or "unknown"),
        "params": params,
        "duration": params.get("duration") or meta.get("duration"),
        "model": params.get("model") or meta.get("model"),
        "created_at": str(meta.get("created_at") or _mtime_iso(audio)),
        "size": size,
        "size_label": _format_size(size),
        "format": audio.suffix.lower().lstrip(".") or "audio",
        "has_meta": bool(meta),
    }


def list_tracks(*, limit: int = 200, backend: str | None = None) -> list[dict[str, Any]]:
    """Scan library roots for audio files, newest first."""
    found: set[Path] = set()
    for root in library_roots():
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix.lower() not in AUDIO_SUFFIXES or not entry.is_file():
                continue
            try:
                found.add(entry.resolve())
            except OSError:
                continue

    tracks = [track_from_file(path) for path in found]
    if backend:
        tracks = [t for t in tracks if t["backend"] == backend]
    tracks.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return tracks[: max(1, min(limit, 1000))]


def is_in_library(path: Path) -> bool:
    """True when ``path`` sits inside one of the library roots."""
    for root in library_roots():
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def delete_track(path: Path) -> None:
    """Remove an audio file and its sidecar. Refuses paths outside the library."""
    target = path.expanduser().resolve()
    if not is_in_library(target):
        raise ValueError(f"Refusing to delete outside the library: {target}")
    if target.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError(f"Not an audio file: {target}")
    target.unlink(missing_ok=True)
    meta_path_for(target).unlink(missing_ok=True)
