# soundcraft

[日本語](README.ja.md)

CLI tool for generating instrumental music from text prompts via MusicGen and Lyria3.

Text input (Japanese/English) → LLM prompt refinement → MusicGen or Lyria3 → audio files

## Setup

```bash
uv venv
uv pip install -e .
source .venv/bin/activate
```

Create `.env`:

```
REPLICATE_API_TOKEN=your_token_here
GEMINI_API_KEY=your_gemini_api_key_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

## Usage

```bash
# Basic (Japanese input OK)
soundcraft "暗い、鼓動、インスタレーション"

# Skip LLM refinement
soundcraft "dark ambient drone, heavy reverb" --raw

# Use Lyria3 backend
soundcraft "energetic pop beat, bright" -b lyria3

# Options
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-b` | Backend: `musicgen`, `lyria3` | `musicgen` |
| `-m` | Model (MusicGen): `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | Duration in seconds (MusicGen) | `30` |
| `-n` | Number of variations | `3` |
| `-o` | Output directory | `output/` |
| `--raw` | Skip LLM prompt refinement | off |

## Backends

| Backend | API | Output | Best for |
|---------|-----|--------|----------|
| MusicGen | Replicate | WAV | Ambient, experimental, dark textures |
| Lyria3 | Gemini | MP3 (30s clip) | Pop, bright, melodic |

## Output

Files are named by the first 4 words of the prompt + sequence number:

```
output/dark_ambient_drone_with_001.wav   # MusicGen
output/energetic_pop_beat_bright_001.mp3 # Lyria3
```

## Architecture

```
Text input
  ↓
LM Studio (prompt refinement, optional)
  ↓
MusicGen (Replicate API) → WAV
  or
Lyria3 (Gemini API)      → MP3
  ↓
Audio files saved to output/
```

## Requirements

- Python 3.10+ / [uv](https://docs.astral.sh/uv/)
- [Replicate API token](https://replicate.com/account/api-tokens) (for MusicGen)
- [Gemini API key](https://aistudio.google.com/apikey) (for Lyria3)
- LM Studio (optional, for prompt refinement)
