"""Shared generation pipeline used by CLI and API server."""

from dataclasses import dataclass
from pathlib import Path

from soundcraft.config import (
    DEFAULT_BACKEND,
    DEFAULT_DURATION,
    DEFAULT_MODEL,
    default_output_dir,
)
from soundcraft.generate import generate_music
from soundcraft.generate_lyria import generate_music_lyria
from soundcraft.library import write_track_meta
from soundcraft.prompt import refine_prompt


@dataclass
class GenerateResult:
    input: str
    prompt: str
    backend: str
    files: list[Path]


def run_generate(
    text: str,
    *,
    backend: str = DEFAULT_BACKEND,
    model: str = DEFAULT_MODEL,
    duration: int = DEFAULT_DURATION,
    count: int = 1,
    output_dir: Path | None = None,
    raw: bool = False,
) -> GenerateResult:
    out = output_dir if output_dir is not None else default_output_dir()
    prompt = text if raw else refine_prompt(text)

    files: list[Path] = []
    for _ in range(count):
        if backend == "lyria3":
            path = generate_music_lyria(prompt=prompt, output_dir=out)
        else:
            path = generate_music(
                prompt=prompt,
                model_version=model,
                duration=duration,
                output_dir=out,
            )
        resolved = path.resolve()
        try:
            write_track_meta(
                resolved,
                input_text=text,
                prompt=prompt,
                backend=backend,
                model=None if backend == "lyria3" else model,
                duration=None if backend == "lyria3" else duration,
            )
        except OSError:
            pass
        files.append(resolved)

    return GenerateResult(
        input=text,
        prompt=prompt,
        backend=backend,
        files=files,
    )
