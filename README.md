# soundcraft

[日本語](README.ja.md)

MusicGen CLI tool for generating instrumental music from text prompts.

Text input (Japanese/English) → LLM prompt refinement → MusicGen (Replicate API) → WAV files

## Setup

```bash
uv venv
uv pip install -e .
source .venv/bin/activate
```

Create `.env`:

```
REPLICATE_API_TOKEN=your_token_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

## Usage

```bash
# Basic (Japanese input OK)
soundcraft "暗い、鼓動、インスタレーション"

# Skip LLM refinement
soundcraft "dark ambient drone, heavy reverb" --raw

# Options
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-m` | Model: `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | Duration (seconds) | `30` |
| `-n` | Number of variations | `3` |
| `-o` | Output directory | `output/` |
| `--raw` | Skip LLM prompt refinement | off |

## Output

Files are named by the first 4 words of the prompt + sequence number:

```
output/dark_ambient_drone_with_001.wav
output/dark_ambient_drone_with_002.wav
output/dark_ambient_drone_with_003.wav
```

## Architecture

```
Text input
  ↓
LM Studio (prompt refinement, optional)
  ↓
Replicate API (MusicGen)
  ↓
WAV files saved to output/
```

## Requirements

- Python 3.10+ / [uv](https://docs.astral.sh/uv/)
- [Replicate API token](https://replicate.com/account/api-tokens)
- LM Studio (optional, for prompt refinement)
