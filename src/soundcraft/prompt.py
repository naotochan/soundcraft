"""Optional prompt refinement through a local OpenAI-compatible LLM.

Refinement is a convenience, never a dependency: if the endpoint is unset or
unreachable the raw input is passed through so a generation never fails because
LM Studio happens to be closed.
"""

from __future__ import annotations

import logging

import requests

from soundcraft import settings

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a music prompt engineer for text-to-music models.
Convert the user's input into a concise English prompt.

CRITICAL: You MUST reply in English only. Never use Japanese or any other language.

Rules:
- Output ONLY the English prompt text, no explanation, no quotes
- Use music terms: genre, mood, instruments, tempo, texture, effects
- Under 60 words
- Favour instrumental, ambient and electronic styles
- Include audio characteristics (reverb, distortion, lo-fi, etc.) when relevant

Example input: 暗い、鼓動、インスタレーション
Example output: Dark ambient drone with deep heartbeat pulse, heavy reverb, slow tempo, layered synth textures, immersive installation soundscape, subtle distortion
"""  # noqa: E501


def refiner_available() -> bool:
    return bool(settings.get("LM_STUDIO_URL") and settings.get("LM_STUDIO_MODEL"))


def refine_prompt(raw_input: str) -> str:
    """Return a refined prompt, or the input unchanged if refinement is not possible."""
    if not refiner_available():
        return raw_input

    url = settings.get("LM_STUDIO_URL").rstrip("/")
    try:
        resp = requests.post(
            f"{url}/v1/chat/completions",
            json={
                "model": settings.get("LM_STUDIO_MODEL"),
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": raw_input},
                ],
                "temperature": 0.7,
                "max_tokens": 150,
            },
            timeout=30,
        )
        resp.raise_for_status()
        refined = resp.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as e:
        log.warning("Prompt refinement unavailable (%s); using the raw prompt.", e)
        return raw_input
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected LLM response (%s); using the raw prompt.", e)
        return raw_input

    return refined or raw_input
