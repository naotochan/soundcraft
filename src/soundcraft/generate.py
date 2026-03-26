import re
import time
from pathlib import Path

import requests

from soundcraft.config import REPLICATE_API_TOKEN, REPLICATE_MODEL_VERSION

API_BASE = "https://api.replicate.com/v1/predictions"


def generate_music(
    prompt: str,
    model_version: str,
    duration: int,
    output_dir: Path,
) -> Path:
    if not REPLICATE_API_TOKEN:
        raise SystemExit("Error: REPLICATE_API_TOKEN is not set. Create a .env file or set the environment variable.")

    headers = {
        "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    resp = requests.post(API_BASE, headers=headers, json={
        "version": REPLICATE_MODEL_VERSION,
        "input": {
            "prompt": prompt,
            "model_version": model_version,
            "duration": duration,
            "output_format": "wav",
            "normalization_strategy": "peak",
        },
    }, timeout=30)
    resp.raise_for_status()
    prediction = resp.json()

    poll_url = prediction["urls"]["get"]
    output_url = _poll_until_done(poll_url, headers)

    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _prompt_to_slug(prompt)
    seq = _next_seq(output_dir, slug)
    filename = f"{slug}_{seq:03d}.wav"
    output_path = output_dir / filename

    _download_file(output_url, output_path)
    return output_path


def _download_file(url: str, dest: Path) -> None:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def _prompt_to_slug(prompt: str, max_words: int = 4) -> str:
    words = re.findall(r'[a-zA-Z]+', prompt.lower())
    if not words:
        return "generated"
    return "_".join(words[:max_words])


def _next_seq(output_dir: Path, slug: str) -> int:
    existing = list(output_dir.glob(f"{slug}_*.*"))
    if not existing:
        return 1
    nums = []
    for p in existing:
        match = re.search(r'_(\d{3})\.\w+$', p.name)
        if match:
            nums.append(int(match.group(1)))
    return max(nums, default=0) + 1


def _poll_until_done(url: str, headers: dict, timeout: float = 300) -> str:
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data["status"]

        if status == "succeeded":
            output = data["output"]
            if isinstance(output, list):
                return output[0]
            return output
        if status == "failed":
            raise RuntimeError(f"Generation failed: {data.get('error', 'unknown error')}")
        if status == "canceled":
            raise RuntimeError("Generation was canceled")

        time.sleep(2)

    raise RuntimeError(f"Generation timed out after {timeout}s")
