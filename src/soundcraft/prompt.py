import requests

from soundcraft.config import get_lm_studio_model, get_lm_studio_url

SYSTEM_PROMPT = """\
You are a music prompt engineer for MusicGen (text-to-music AI).
Convert the user's input into a concise English prompt for MusicGen.

CRITICAL: You MUST reply in English only. Never use Japanese or any other language.

Rules:
- Output ONLY the English prompt text, no explanation, no quotes
- Use music terms: genre, mood, instruments, tempo, texture, effects
- Under 60 words
- Focus on instrumental/ambient/electronic styles
- Include audio characteristics (reverb, distortion, lo-fi, etc.) when relevant

Example input: 暗い、鼓動、インスタレーション
Example output: Dark ambient drone with deep heartbeat pulse, heavy reverb, slow tempo, layered synth textures, immersive installation soundscape, subtle distortion
"""


def refine_prompt(raw_input: str) -> str:
    try:
        resp = requests.post(
            f"{get_lm_studio_url()}/v1/chat/completions",
            json={
                "model": get_lm_studio_model(),
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
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.ConnectionError:
        print("Warning: LLM server unreachable. Using raw prompt.")
        return raw_input
    except requests.HTTPError as e:
        print(f"Warning: LLM request failed ({e}). Using raw prompt.")
        return raw_input
