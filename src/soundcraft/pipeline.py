"""Generation pipeline shared by the CLI, the HTTP API and the GUI."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soundcraft.library import write_track_meta
from soundcraft.naming import unique_path
from soundcraft.paths import default_output_dir
from soundcraft.prompt import refine_prompt
from soundcraft.providers import registry
from soundcraft.providers.base import GenerationRequest, ProviderError

#: Called as ``progress(done, total, path)`` after each clip is written.
Progress = Callable[[int, int, Path], None]


@dataclass
class GenerateResult:
    input: str
    prompt: str
    backend: str
    params: dict[str, Any]
    files: list[Path] = field(default_factory=list)


def resolve_backend(backend: str | None) -> str:
    """Normalise a backend id, falling back to the first ready provider."""
    if backend and registry.has(backend):
        return backend
    if backend:
        raise ProviderError(
            f"Unknown backend {backend!r}. Available: {', '.join(registry.ids())}"
        )
    return registry.default_id()


def run_generate(
    text: str,
    *,
    backend: str | None = None,
    params: dict[str, Any] | None = None,
    count: int = 1,
    output_dir: Path | None = None,
    raw: bool = False,
    progress: Progress | None = None,
) -> GenerateResult:
    """Refine the prompt once, then generate ``count`` clips with one provider."""
    provider = registry.get(resolve_backend(backend))
    resolved_params = provider.coerce_params(params)

    out = Path(output_dir) if output_dir is not None else default_output_dir()
    prompt = text if raw else refine_prompt(text)
    request = GenerationRequest(prompt=prompt, params=resolved_params)

    files: list[Path] = []
    for index in range(count):
        audio = provider.generate(request)
        path = unique_path(out, prompt, audio.suffix)
        path.write_bytes(audio.data)
        resolved = path.resolve()

        # A sidecar that cannot be written must never cost us the audio.
        with suppress(OSError):
            write_track_meta(
                resolved,
                input_text=text,
                prompt=prompt,
                backend=provider.id,
                params=resolved_params,
                extra=audio.extra,
            )

        files.append(resolved)
        if progress is not None:
            progress(index + 1, count, resolved)

    return GenerateResult(
        input=text,
        prompt=prompt,
        backend=provider.id,
        params=resolved_params,
        files=files,
    )
