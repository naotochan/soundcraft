"""Hugging Face Inference API — open models with only a token to set up.

The lightest possible on-ramp: no GPU, no install, a free tier. Useful for
hearing something in the first minute, then moving to ComfyUI or local once the
piece needs to run unattended.
"""

from __future__ import annotations

import time

import requests

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

DEFAULT_BASE = "https://router.huggingface.co/hf-inference/models"

#: Attempts against a cold model, which answers 503 while it loads.
RETRIES = 4

MODELS = (
    Option("facebook/musicgen-small", "MusicGen small"),
    Option("facebook/musicgen-medium", "MusicGen medium"),
    Option("facebook/musicgen-large", "MusicGen large"),
    Option("facebook/musicgen-stereo-small", "MusicGen stereo small"),
)

CONTENT_SUFFIX = {
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
}


class HuggingFaceProvider(Provider):
    id = "huggingface"
    label = "Hugging Face"
    summary = (
        "Open models on Hugging Face's hosted inference, with a free tier. "
        "Fastest way to hear something without installing anything."
    )
    tags = ("hosted", "free-tier", "no-gpu-needed")
    docs_url = "https://huggingface.co/docs/api-inference"
    speed = "20s–2min (slower on a cold model)"

    settings = (
        SettingSpec(
            key="HF_API_TOKEN",
            label="Hugging Face token",
            secret=True,
            url="https://huggingface.co/settings/tokens",
            help="A read token is enough.",
            placeholder="hf_…",
        ),
        SettingSpec(
            key="HF_INFERENCE_BASE",
            label="Inference endpoint",
            default=DEFAULT_BASE,
            help="Point at a dedicated Inference Endpoint to bypass the shared queue.",
            placeholder=DEFAULT_BASE,
        ),
    )

    params = (
        ParamSpec(
            name="model",
            label="Model",
            type="select",
            default="facebook/musicgen-small",
            options=MODELS,
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
            help="Honoured only by models that accept a length parameter.",
        ),
    )

    def coerce_params(self, raw: dict | None) -> dict:
        """Allow any Hub model id, not only the listed ones."""
        raw = dict(raw or {})
        model = raw.pop("model", None)
        params = super().coerce_params(raw)
        params["model"] = str(model) if model else "facebook/musicgen-small"
        return params

    def availability(self) -> Availability:
        if not settings.is_set("HF_API_TOKEN"):
            return Availability(
                False,
                "Hugging Face token is not set.",
                "Create a read token at huggingface.co/settings/tokens.",
            )
        return READY

    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        token = settings.get("HF_API_TOKEN")
        if not token:
            raise ProviderUnavailable("HF_API_TOKEN is not set. Add it in Settings.")

        base = settings.get("HF_INFERENCE_BASE").rstrip("/")
        model = str(request.get("model", "facebook/musicgen-small"))
        # A dedicated Inference Endpoint already points at one model; only the
        # shared router needs the model appended.
        url = base if base.endswith(f"/{model}") else f"{base}/{model}"

        payload = {
            "inputs": request.prompt,
            "parameters": {"duration": int(request.get("duration", 15))},
            "options": {"wait_for_model": True},
        }
        headers = {"Authorization": f"Bearer {token}"}

        # A cold model answers 503 with an estimated load time; retry a few times.
        for attempt in range(RETRIES):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=300)
            except requests.RequestException as e:
                raise ProviderError(f"Could not reach Hugging Face: {e}") from e

            if resp.status_code == 503:
                if attempt < RETRIES - 1:
                    time.sleep(_estimated_wait(resp, attempt))
                    continue
                raise ProviderError(
                    f"{model} is still loading on Hugging Face. Wait a moment and retry."
                )
            if resp.status_code == 401:
                raise ProviderUnavailable(
                    "Hugging Face rejected the token. Check it in Settings."
                )
            if resp.status_code == 404:
                raise ProviderError(
                    f"{model} is not available on hosted inference. Try another model "
                    "or run it locally."
                )
            if resp.status_code >= 400:
                raise ProviderError(f"Hugging Face error {resp.status_code}: {_detail(resp)}")

            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            if content_type.startswith("application/json"):
                raise ProviderError(f"Hugging Face returned no audio: {_detail(resp)}")
            if not resp.content:
                raise ProviderError("Hugging Face returned an empty response.")

            return GeneratedAudio(
                data=resp.content,
                suffix=CONTENT_SUFFIX.get(content_type, ".flac"),
                extra={"model": model},
            )

        raise AssertionError("unreachable: every branch above returns or raises")


def _estimated_wait(resp: requests.Response, attempt: int) -> float:
    try:
        estimated = float(resp.json().get("estimated_time", 0))
    except (ValueError, TypeError, AttributeError):
        estimated = 0.0
    return min(max(estimated, 5.0 * (attempt + 1)), 60.0)


def _detail(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except ValueError:
        return resp.text[:500]
    if not isinstance(payload, dict):
        return str(payload)[:500]
    return str(payload.get("error") or payload)[:500]


register(HuggingFaceProvider())
