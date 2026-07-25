# soundcraft

[日本語](README.ja.md)

CLI, local GUI, and API for generating instrumental music from text prompts via MusicGen and Lyria3.

```
Text → (optional) LM Studio refine → MusicGen or Lyria3 → audio files
```

Distribution is **source-first** (clone → run). There is no packaged macOS `.app`; the browser GUI is the app UI.

## Quick start

```bash
git clone https://github.com/naotochan/soundcraft.git
cd soundcraft

uv venv
uv pip install -e .
source .venv/bin/activate

cp .env.example .env
# edit .env — set at least one of:
#   REPLICATE_API_TOKEN  (MusicGen)
#   GEMINI_API_KEY       (Lyria3)

soundcraft gui
```

This starts the local server and opens `http://127.0.0.1:8765/` in your browser.

| Need | Command |
|------|---------|
| GUI | `soundcraft gui` |
| API only (TouchDesigner, etc.) | `soundcraft serve` |
| One-shot CLI | `soundcraft "暗い、鼓動、インスタレーション"` |

## `.env`

```
REPLICATE_API_TOKEN=your_token_here
GEMINI_API_KEY=your_gemini_api_key_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

LM Studio is optional (prompt refinement). Use `--raw` to skip it.

## CLI

```bash
soundcraft "暗い、鼓動、インスタレーション"
soundcraft "dark ambient drone, heavy reverb" --raw
soundcraft "energetic pop beat, bright" -b lyria3
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

| Flag | Description | Default |
|------|-------------|---------|
| `-b` | Backend: `musicgen`, `lyria3` | `musicgen` |
| `-m` | Model (MusicGen): `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | Duration in seconds (MusicGen) | `30` |
| `-n` | Number of variations | `3` |
| `-o` | Output directory | `output/` |
| `--raw` | Skip LLM prompt refinement | off |

## Local API

Same process as the GUI (`serve` / `gui`). Default: `http://127.0.0.1:8765`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Browser GUI |
| `GET` | `/health` | Liveness check |
| `POST` | `/generate` | Sync generation |
| `POST` | `/jobs` | Async generation (best for TD) |
| `GET` | `/jobs/{id}` | Poll job |
| `GET` | `/media?path=` | Stream a file under `output/` |

```bash
curl -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"暗い、鼓動","backend":"musicgen","count":1}'
```

Response `files` are absolute paths (load in TD via `Audio File In CHOP`, etc.).

## Backends

| Backend | API | Output | Best for |
|---------|-----|--------|----------|
| MusicGen | Replicate | WAV | Ambient, experimental, dark textures |
| Lyria3 | Gemini | MP3 (30s clip) | Pop, bright, melodic |

## Output

```
output/dark_ambient_drone_with_001.wav   # MusicGen
output/energetic_pop_beat_bright_001.mp3 # Lyria3
```

## Requirements

- Python 3.10+ / [uv](https://docs.astral.sh/uv/)
- [Replicate API token](https://replicate.com/account/api-tokens) (MusicGen)
- [Gemini API key](https://aistudio.google.com/apikey) (Lyria3)
- LM Studio (optional)
