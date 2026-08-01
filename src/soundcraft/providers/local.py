"""On-device generation with MusicGen — no API key, no network, no quota.

Installed separately because it pulls in PyTorch::

    uv pip install -e ".[local]"

The model stays resident between requests, so the first generation pays the
load cost and later ones do not. That matters for installations that run for
weeks: after warm-up there is nothing left to fail over the network.
"""

from __future__ import annotations

import io
import wave
from typing import Any

from soundcraft import settings
from soundcraft.providers.base import (
    READY,
    Availability,
    GeneratedAudio,
    GenerationRequest,
    Option,
    ParamSpec,
    Provider,
    ProviderError,
    ProviderUnavailable,
    SettingSpec,
)
from soundcraft.providers.registry import register

#: MusicGen emits 50 audio tokens per second of output.
TOKENS_PER_SECOND = 50

MODELS = (
    Option("facebook/musicgen-small", "MusicGen small (300M · fastest)"),
    Option("facebook/musicgen-medium", "MusicGen medium (1.5B)"),
    Option("facebook/musicgen-large", "MusicGen large (3.3B · best)"),
    Option("facebook/musicgen-stereo-small", "MusicGen stereo small"),
    Option("facebook/musicgen-stereo-medium", "MusicGen stereo medium"),
    Option("facebook/musicgen-stereo-large", "MusicGen stereo large"),
)


def _pick_device(preference: str) -> str:
    import torch

    if preference and preference != "auto":
        return preference
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _to_wav_bytes(samples, sample_rate: int) -> bytes:
    """Encode a float array shaped (channels, frames) as 16-bit PCM WAV."""
    import numpy as np

    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 1:
        array = array[np.newaxis, :]
    peak = float(np.max(np.abs(array))) if array.size else 0.0
    if peak > 1.0:
        array = array / peak
    interleaved = np.clip(array.T, -1.0, 1.0)
    pcm = (interleaved * 32767.0).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(array.shape[0])
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


class LocalMusicGenProvider(Provider):
    id = "local"
    label = "Local (MusicGen)"
    summary = (
        "Runs MusicGen on this machine. No API key, no per-generation cost and "
        "no internet after the first model download — the safe choice for a "
        "long-running installation."
    )
    tags = ("offline", "no-api-key", "gpu-optional")
    docs_url = "https://huggingface.co/facebook/musicgen-small"
    speed = "Seconds on a GPU, minutes on CPU"

    settings = (
        SettingSpec(
            key="LOCAL_DEVICE",
            label="Compute device",
            default="auto",
            help="auto, cpu, cuda or mps. 'auto' prefers CUDA, then Apple MPS.",
            placeholder="auto",
        ),
    )

    params = (
        ParamSpec(
            name="model",
            label="Model",
            type="select",
            default="facebook/musicgen-small",
            options=MODELS,
            help="Larger models sound better and take proportionally longer.",
        ),
        ParamSpec(
            name="duration",
            label="Duration",
            type="number",
            default=15,
            minimum=1,
            maximum=120,
            step=1,
            unit="s",
        ),
        ParamSpec(
            name="guidance_scale",
            label="Guidance",
            type="number",
            default=3.0,
            minimum=1.0,
            maximum=10.0,
            step=0.5,
            help="Higher values follow the prompt more literally.",
        ),
        ParamSpec(
            name="seed",
            label="Seed",
            type="number",
            default=None,
            minimum=0,
            maximum=2**53 - 1,
            step=1,
            optional=True,
        ),
    )

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], Any] = {}

    # -- availability ----------------------------------------------------

    @staticmethod
    def dependencies_installed() -> bool:
        from importlib.util import find_spec

        return all(find_spec(mod) is not None for mod in ("torch", "transformers", "numpy"))

    def availability(self) -> Availability:
        if not self.dependencies_installed():
            return Availability(
                False,
                "PyTorch and Transformers are not installed.",
                'Install the local extra: uv pip install -e ".[local]"',
            )
        return READY

    def on_settings_changed(self) -> None:
        self._cache.clear()

    # -- generation ------------------------------------------------------

    def _load(self, model_id: str, device: str):
        key = (model_id, device)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        try:
            processor = AutoProcessor.from_pretrained(model_id)
            model = MusicgenForConditionalGeneration.from_pretrained(model_id)
        except Exception as e:
            raise ProviderError(
                f"Could not load {model_id}: {e}. The first run downloads several "
                "GB — check your connection and disk space."
            ) from e

        model = model.to(device)
        model.eval()
        self._cache[key] = (processor, model)
        return processor, model

    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        if not self.dependencies_installed():
            raise ProviderUnavailable(
                'Local generation needs PyTorch. Install it with: uv pip install -e ".[local]"'
            )

        import torch

        model_id = str(request.get("model", "facebook/musicgen-small"))
        device = _pick_device(settings.get("LOCAL_DEVICE", "auto"))
        processor, model = self._load(model_id, device)

        seed = request.params.get("seed")
        if seed is not None:
            torch.manual_seed(int(seed))

        duration = int(request.get("duration", 15))
        inputs = processor(text=[request.prompt], padding=True, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        try:
            with torch.inference_mode():
                audio = model.generate(
                    **inputs,
                    do_sample=True,
                    guidance_scale=float(request.get("guidance_scale", 3.0)),
                    max_new_tokens=duration * TOKENS_PER_SECOND,
                )
        except RuntimeError as e:
            hint = ""
            if "out of memory" in str(e).lower():
                hint = " Try a smaller model or a shorter duration."
            raise ProviderError(f"Generation failed on {device}: {e}.{hint}") from e

        sample_rate = model.config.audio_encoder.sampling_rate
        data = _to_wav_bytes(audio[0].detach().float().cpu().numpy(), sample_rate)
        return GeneratedAudio(
            data=data,
            suffix=".wav",
            extra={"device": device, "seed": seed, "sample_rate": sample_rate},
        )


register(LocalMusicGenProvider())
