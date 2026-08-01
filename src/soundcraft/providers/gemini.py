"""Google Lyria via the Gemini API — melodic, song-like clips."""

from __future__ import annotations

from soundcraft import settings
from soundcraft.providers.base import (
    READY,
    Availability,
    GeneratedAudio,
    GenerationRequest,
    Provider,
    ProviderError,
    ProviderUnavailable,
    SettingSpec,
    has_module,
)
from soundcraft.providers.registry import register

DEFAULT_MODEL = "lyria-3-clip-preview"

#: The API has returned more than one container over time; name the file for
#: what it actually is so players and the library agree.
MIME_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
}


class LyriaProvider(Provider):
    id = "lyria"
    label = "Lyria (Gemini)"
    summary = (
        "Google's Lyria through the Gemini API. Fixed-length clips, strongest on "
        "melodic and tonal material."
    )
    tags = ("hosted", "melodic", "free-tier")
    docs_url = "https://ai.google.dev/gemini-api/docs"
    speed = "~30s per clip"

    settings = (
        SettingSpec(
            key="GEMINI_API_KEY",
            label="Gemini API key",
            secret=True,
            url="https://aistudio.google.com/apikey",
            help="Required for Lyria generation.",
            placeholder="AIza…",
        ),
        SettingSpec(
            key="LYRIA_MODEL",
            label="Lyria model",
            default=DEFAULT_MODEL,
            help="Override if Google ships a newer clip model.",
            placeholder=DEFAULT_MODEL,
        ),
    )

    #: Clip length and sampling are fixed by the API; nothing to expose.
    params = ()

    def __init__(self) -> None:
        self._client = None
        self._client_key: str | None = None

    def on_settings_changed(self) -> None:
        self._client = None
        self._client_key = None

    @staticmethod
    def dependencies_installed() -> bool:
        return has_module("google.genai")

    def availability(self) -> Availability:
        if not self.dependencies_installed():
            return Availability(
                False,
                "google-genai is not installed.",
                "Install it with: uv pip install google-genai",
            )
        if not settings.is_set("GEMINI_API_KEY"):
            return Availability(
                False,
                "Gemini API key is not set.",
                "Create a key at aistudio.google.com/apikey and paste it in Settings.",
            )
        return READY

    def _get_client(self):
        from google import genai

        key = settings.get("GEMINI_API_KEY")
        if not key:
            raise ProviderUnavailable("GEMINI_API_KEY is not set. Add it in Settings.")
        if self._client is None or self._client_key != key:
            self._client = genai.Client(api_key=key)
            self._client_key = key
        return self._client

    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        if not self.dependencies_installed():
            raise ProviderUnavailable(
                "Lyria needs google-genai. Install it with: uv pip install google-genai"
            )

        from google.genai import types

        client = self._get_client()
        model = settings.get("LYRIA_MODEL", DEFAULT_MODEL)

        try:
            response = client.models.generate_content(
                model=model,
                contents=request.prompt,
                config=types.GenerateContentConfig(response_modalities=["AUDIO"]),
            )
        except Exception as e:
            raise ProviderError(f"Lyria request failed: {e}") from e

        candidates = response.candidates or []
        if not candidates or not candidates[0].content or not candidates[0].content.parts:
            raise ProviderError(
                "Lyria returned no audio. The prompt was most likely blocked by a "
                "safety filter — try rewording it."
            )

        for part in candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                mime = (part.inline_data.mime_type or "").split(";")[0].strip()
                return GeneratedAudio(
                    data=part.inline_data.data,
                    suffix=MIME_SUFFIX.get(mime, ".mp3"),
                    extra={"model": model, "mime_type": mime},
                )

        raise ProviderError("Lyria returned a response with no audio payload.")


register(LyriaProvider())
