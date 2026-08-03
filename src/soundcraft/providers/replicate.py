"""Replicate — hosted inference for a range of open music models.

Any Replicate model can be used, not just MusicGen: the provider reads the
model's own OpenAPI input schema and maps prompt/duration/seed onto whatever
field names that model actually uses. Add more with the ``REPLICATE_MODELS``
setting — no code change needed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

API_ROOT = "https://api.replicate.com/v1"

#: Curated starting points. Users add their own via REPLICATE_MODELS.
PRESETS: tuple[Option, ...] = (
    Option("meta/musicgen", "MusicGen (Meta) — ambient, textural"),
    Option("stackadoc/stable-audio-open-1.0", "Stable Audio Open — sound design, loops"),
    Option("lucataco/ace-step", "ACE-Step — songs with structure"),
    Option("riffusion/riffusion", "Riffusion — quick sketches"),
)

PROMPT_KEYS = ("prompt", "text", "tags", "prompt_a", "description")
DURATION_KEYS = ("duration", "seconds_total", "seconds", "length", "audio_length")
SEED_KEYS = ("seed",)


class ReplicateProvider(Provider):
    id = "replicate"
    label = "Replicate"
    summary = (
        "Hosted GPUs for open music models. Nothing to install, pay per second. "
        "Good for trying models out before committing to running them locally."
    )
    tags = ("hosted", "pay-per-use", "no-gpu-needed")
    docs_url = "https://replicate.com/collections/text-to-music"
    speed = "30s–2min per clip"

    settings = (
        SettingSpec(
            key="REPLICATE_API_TOKEN",
            label="Replicate API token",
            secret=True,
            url="https://replicate.com/account/api-tokens",
            help="Required for hosted generation on Replicate.",
            placeholder="r8_…",
        ),
        SettingSpec(
            key="REPLICATE_MODELS",
            label="Extra Replicate models",
            help=(
                "Comma- or newline-separated owner/name refs to add to the model "
                "list, e.g. sakemin/musicgen-stereo-chord. Pin a version with "
                "owner/name:version."
            ),
            placeholder="owner/name, owner/name:version",
        ),
    )

    params = (
        ParamSpec(
            name="model",
            label="Model",
            type="select",
            default="meta/musicgen",
            options=PRESETS,
        ),
        ParamSpec(
            name="duration",
            label="Duration",
            type="number",
            default=30,
            minimum=1,
            maximum=300,
            step=1,
            unit="s",
            help="Ignored by models with a fixed clip length.",
        ),
        ParamSpec(
            name="musicgen_variant",
            label="MusicGen variant",
            type="select",
            default="melody-large",
            options=(
                Option("melody-large", "melody-large"),
                Option("stereo-melody-large", "stereo-melody-large"),
                Option("large", "large"),
                Option("stereo-large", "stereo-large"),
            ),
            help="Only applies to meta/musicgen.",
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
        self._schema_cache: dict[str, dict[str, Any]] = {}

    # -- configuration ---------------------------------------------------

    def custom_models(self) -> list[str]:
        raw = settings.get("REPLICATE_MODELS", "")
        parts = [p.strip() for chunk in raw.split("\n") for p in chunk.split(",")]
        return [p for p in parts if p]

    def model_options(self) -> list[dict[str, str]]:
        options = [o.as_dict() for o in PRESETS]
        known = {o["value"] for o in options}
        for ref in self.custom_models():
            if ref not in known:
                known.add(ref)
                options.append({"value": ref, "label": ref})
        return options

    def describe(self) -> dict[str, Any]:
        described = super().describe()
        for param in described["params"]:
            if param["name"] == "model":
                param["options"] = self.model_options()
        return described

    def availability(self) -> Availability:
        if not settings.is_set("REPLICATE_API_TOKEN"):
            return Availability(
                False,
                "Replicate API token is not set.",
                "Create a token at replicate.com/account/api-tokens and paste it in Settings.",
            )
        return READY

    def coerce_params(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        """Accept any model ref the user configured, not only the presets."""
        raw = dict(raw or {})
        model = raw.pop("model", None)
        params = super().coerce_params({k: v for k, v in raw.items() if k != "model"})
        params["model"] = str(model) if model else "meta/musicgen"
        if "/" not in params["model"]:
            raise ValueError(
                f"Replicate model must look like owner/name, got {params['model']!r}"
            )
        return params

    def on_settings_changed(self) -> None:
        self._schema_cache.clear()

    # -- schema introspection --------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = settings.get("REPLICATE_API_TOKEN")
        if not token:
            raise ProviderUnavailable(
                "REPLICATE_API_TOKEN is not set. Add it in Settings."
            )
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def input_fields(self, ref: str) -> dict[str, Any]:
        """Input properties declared by the model, so we map fields correctly.

        Only successful lookups are cached: caching a network blip would pin
        that model to guessed field names for the life of the process.
        """
        if ref in self._schema_cache:
            return self._schema_cache[ref]

        owner_name, _, version = ref.partition(":")
        url = (
            f"{API_ROOT}/models/{owner_name}/versions/{version}"
            if version
            else f"{API_ROOT}/models/{owner_name}"
        )

        try:
            resp = requests.get(url, headers=self._headers(), timeout=20)
            if not resp.ok:
                return {}
            body = resp.json()
            # The versions endpoint returns the version object directly.
            version_obj = body if version else body.get("latest_version") or {}
            schemas = (
                version_obj.get("openapi_schema", {})
                .get("components", {})
                .get("schemas", {})
            )
            fields = (schemas.get("Input") or {}).get("properties") or {}
        except (requests.RequestException, ValueError, AttributeError):
            return {}  # Fall back to conventional names, and retry next time.

        self._schema_cache[ref] = fields
        return fields

    def build_input(self, ref: str, request: GenerationRequest) -> dict[str, Any]:
        fields = self.input_fields(ref)

        def pick(candidates: tuple[str, ...], fallback: str | None) -> str | None:
            if not fields:
                return fallback
            for name in candidates:
                if name in fields:
                    return name
            return None

        payload: dict[str, Any] = {}
        prompt_key = pick(PROMPT_KEYS, "prompt")
        if prompt_key:
            payload[prompt_key] = request.prompt

        duration = request.params.get("duration")
        duration_key = pick(DURATION_KEYS, "duration")
        if duration_key and duration:
            payload[duration_key] = int(duration)

        seed = request.params.get("seed")
        # Falls back to "seed" like the other fields: a model that rejects it
        # says so, which beats silently discarding the one input whose whole
        # purpose is reproducibility.
        seed_key = pick(SEED_KEYS, "seed")
        if seed_key and seed is not None:
            payload[seed_key] = int(seed)

        if ref.split(":")[0] == "meta/musicgen":
            payload.setdefault("model_version", request.get("musicgen_variant", "melody-large"))
            payload.setdefault("output_format", "wav")
            payload.setdefault("normalization_strategy", "peak")

        if not payload:
            raise ProviderError(
                f"Could not work out how to send a prompt to {ref}. "
                "It may not be a text-to-audio model."
            )
        return payload

    # -- execution -------------------------------------------------------

    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        ref = str(request.get("model", "meta/musicgen"))
        headers = self._headers()
        payload = self.build_input(ref, request)

        if ":" in ref:
            url = f"{API_ROOT}/predictions"
            body = {"version": ref.split(":", 1)[1], "input": payload}
        else:
            url = f"{API_ROOT}/models/{ref}/predictions"
            body = {"input": payload}

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=60)
        except requests.RequestException as e:
            raise ProviderError(f"Could not reach Replicate: {e}") from e

        if resp.status_code >= 400:
            raise ProviderError(f"Replicate rejected the request: {_detail(resp)}")

        try:
            prediction = resp.json()
        except ValueError as e:
            # requests' JSONDecodeError subclasses OSError; without this it
            # would surface as a disk error.
            raise ProviderError("Replicate returned a non-JSON response.") from e
        if not isinstance(prediction, dict):
            raise ProviderError(f"Unexpected response from Replicate: {prediction!r:.200}")
        poll_url = (prediction.get("urls") or {}).get("get")
        if not poll_url:
            raise ProviderError("Replicate did not return a polling URL.")

        output_url = self._poll(poll_url, headers)
        data = self._download(output_url)
        suffix = Path(urlparse(output_url).path).suffix.lower() or ".wav"
        return GeneratedAudio(
            data=data,
            suffix=suffix,
            extra={"model": ref, "seed": request.params.get("seed")},
        )

    def _poll(self, url: str, headers: dict[str, str], timeout: float = 900) -> str:
        """Wait for a prediction, tolerating brief network trouble.

        The prediction is already running and already being billed, so a
        dropped connection is worth retrying rather than abandoning.
        """
        deadline = time.time() + timeout
        delay = 1.0
        failures = 0
        while time.time() < deadline:
            try:
                resp = requests.get(url, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                failures = 0
            except (requests.RequestException, ValueError) as e:
                failures += 1
                if failures >= 4:
                    raise ProviderError(f"Lost contact with Replicate: {e}") from e
                time.sleep(delay)
                continue

            status = data.get("status")
            if status == "succeeded":
                return _first_url(data.get("output"))
            if status == "failed":
                raise ProviderError(
                    f"Replicate generation failed: {data.get('error') or 'unknown error'}"
                )
            if status == "canceled":
                raise ProviderError("Replicate generation was canceled.")

            time.sleep(delay)
            delay = min(delay * 1.3, 5.0)

        raise ProviderError(f"Replicate generation timed out after {timeout:.0f}s.")

    def _download(self, url: str) -> bytes:
        try:
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ProviderError(f"Could not download the result: {e}") from e
        if not resp.content:
            raise ProviderError("Replicate returned an empty file.")
        return resp.content


def _first_url(output: Any) -> str:
    """Models return a bare URL, a list of URLs, or a dict containing one."""
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        return _first_url(output[0])
    if isinstance(output, dict):
        for key in ("audio", "url", "output", "file"):
            if key in output:
                return _first_url(output[key])
    raise ProviderError(f"Unexpected Replicate output shape: {output!r}")


def _detail(resp: requests.Response) -> str:
    try:
        payload = resp.json()
    except ValueError:
        return resp.text[:500]
    if not isinstance(payload, dict):
        return str(payload)[:500]
    return str(payload.get("detail") or payload)[:500]


register(ReplicateProvider())
