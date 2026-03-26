from pathlib import Path

from google import genai
from google.genai import types

from soundcraft.config import GEMINI_API_KEY, LYRIA3_MODEL
from soundcraft.generate import _next_seq, _prompt_to_slug

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate_music_lyria(prompt: str, output_dir: Path) -> Path:
    if not GEMINI_API_KEY:
        raise SystemExit(
            "Error: GEMINI_API_KEY is not set. "
            "Create a .env file or set the environment variable."
        )

    client = _get_client()
    response = client.models.generate_content(
        model=LYRIA3_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
        ),
    )

    candidates = response.candidates
    if not candidates or not candidates[0].content or not candidates[0].content.parts:
        raise RuntimeError(
            "Lyria3 returned no valid candidates. "
            "The prompt may have been blocked by safety filters."
        )

    audio_data = None
    for part in candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            audio_data = part.inline_data.data
            break

    if audio_data is None:
        raise RuntimeError("Lyria3 returned no audio data.")

    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _prompt_to_slug(prompt)
    seq = _next_seq(output_dir, slug)
    filename = f"{slug}_{seq:03d}.mp3"
    output_path = output_dir / filename

    output_path.write_bytes(audio_data)
    return output_path
