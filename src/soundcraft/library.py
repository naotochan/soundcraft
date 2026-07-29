"""Disk-backed generation library (Suno/Udio-style history)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soundcraft.config import APP_NAME, default_output_dir

AUDIO_SUFFIXES = {".wav", ".mp3"}
META_VERSION = 1


def library_roots() -> list[Path]:
    """Directories that may contain generated audio."""
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        roots.append(resolved)

    add(default_output_dir())
    add(Path.cwd() / "output")
    add(Path.home() / "Documents" / APP_NAME / "output")
    return roots


def meta_path_for(audio: Path) -> Path:
    return audio.with_suffix(".json")


def write_track_meta(
    audio: Path,
    *,
    input_text: str,
    prompt: str,
    backend: str,
    model: str | None = None,
    duration: int | None = None,
) -> Path:
    """Write a sidecar JSON next to an audio file."""
    payload: dict[str, Any] = {
        "version": META_VERSION,
        "input": input_text,
        "prompt": prompt,
        "backend": backend,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file": audio.name,
    }
    if model:
        payload["model"] = model
    if duration is not None:
        payload["duration"] = duration

    path = meta_path_for(audio)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_meta(audio: Path) -> dict[str, Any] | None:
    path = meta_path_for(audio)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _guess_backend(audio: Path) -> str:
    return "lyria3" if audio.suffix.lower() == ".mp3" else "musicgen"


def _title_from_name(name: str) -> str:
    stem = Path(name).stem
    # strip trailing _001 style sequence
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        stem = parts[0]
    title = stem.replace("_", " ").strip()
    return title or name


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
    meta = _read_meta(audio) or {}
    try:
        size = audio.stat().st_size
    except OSError:
        size = 0

    prompt = str(meta.get("prompt") or "")
    input_text = str(meta.get("input") or "")
    backend = str(meta.get("backend") or _guess_backend(audio))
    created = str(meta.get("created_at") or _mtime_iso(audio))
    title = prompt or input_text or _title_from_name(audio.name)

    return {
        "id": str(audio.resolve()),
        "path": str(audio.resolve()),
        "name": audio.name,
        "title": title,
        "input": input_text,
        "prompt": prompt,
        "backend": backend,
        "model": meta.get("model"),
        "duration": meta.get("duration"),
        "created_at": created,
        "size": size,
        "size_label": _format_size(size),
        "format": audio.suffix.lower().lstrip(".") or "audio",
        "has_meta": bool(meta),
    }


def list_tracks(*, limit: int = 200) -> list[dict[str, Any]]:
    """Scan library roots for audio files, newest first."""
    found: dict[Path, Path] = {}
    for root in library_roots():
        if not root.is_dir():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in AUDIO_SUFFIXES:
                continue
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            found[resolved] = entry

    tracks = [track_from_file(path) for path in found]
    tracks.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return tracks[: max(1, min(limit, 1000))]
