"""Output file naming — one place, so every provider names files alike."""

from __future__ import annotations

import re
from pathlib import Path

SEQ_RE = re.compile(r"_(\d{3,})\.\w+$")
WORD_RE = re.compile(r"[a-zA-Z0-9]+")
MAX_SLUG_LENGTH = 48


def prompt_to_slug(prompt: str, max_words: int = 4) -> str:
    """A short filesystem-safe stem derived from the prompt."""
    words = WORD_RE.findall(prompt.lower())
    slug = "_".join(words[:max_words])[:MAX_SLUG_LENGTH].strip("_")
    return slug or "generated"


def next_sequence(output_dir: Path, slug: str) -> int:
    """Next free ``_NNN`` suffix for this slug in this directory."""
    highest = 0
    for path in output_dir.glob(f"{slug}_*.*"):
        match = SEQ_RE.search(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def reserve_path(output_dir: Path, prompt: str, suffix: str) -> Path:
    """Claim an unused ``<slug>_NNN<suffix>`` path under ``output_dir``.

    The file is created empty as part of claiming it. Checking `exists()` and
    writing later is not enough: two concurrent generations both see the same
    number free and the second silently overwrites the first.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = prompt_to_slug(prompt)
    seq = next_sequence(output_dir, slug)
    while True:
        candidate = output_dir / f"{slug}_{seq:03d}{suffix}"
        try:
            candidate.touch(exist_ok=False)  # O_CREAT | O_EXCL
        except FileExistsError:
            seq += 1
        else:
            return candidate
