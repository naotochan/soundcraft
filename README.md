# soundcraft

[日本語](README.ja.md)

Generate music from text — as a desktop app, a browser GUI, a CLI, or a local
HTTP API for TouchDesigner and other tools.

```
Text → (optional) local LLM refine → your chosen backend → audio files
```

<p align="center">
  <img src="docs/demo/gui.jpg" alt="soundcraft — prompt to generated audio" width="900" />
</p>

## Backends

soundcraft is not tied to one model. Pick whichever suits how you work — you
only need one, and you can switch per generation.

| Backend | Runs on | Needs | Best for |
|---------|---------|-------|----------|
| **ComfyUI** | your GPU | a running ComfyUI + a workflow | Anything ComfyUI supports — ACE-Step, Stable Audio, MusicGen. No code changes to add a model |
| **Local** | your CPU/GPU | `[local]` extra (PyTorch) | Installations that must keep working offline, with no quota and no cost |
| **Replicate** | hosted | an API token | No GPU, want to try models quickly |
| **Hugging Face** | hosted | a read token | Free tier; the fastest way to hear something |
| **Lyria** | hosted | a Gemini key + `[lyria]` extra | Melodic, tonal, song-like material |

For a long-running piece — a gallery installation, a live set — prefer
**ComfyUI** or **Local**: no network, no rate limit, no bill.

`soundcraft providers` lists them with what each still needs.

## Install

### Desktop app

Download the build for your platform from
[Releases](https://github.com/naotochan/soundcraft/releases), unzip, and run it.

Builds are unsigned:

- **macOS** — right-click `Soundcraft.app` → **Open** → **Open**. Once only.
- **Windows** — SmartScreen warns on first run: **More info** → **Run anyway**.
- **Linux** — `./Soundcraft/Soundcraft`.

### From source

```bash
git clone https://github.com/naotochan/soundcraft.git
cd soundcraft

uv venv && source .venv/bin/activate
uv pip install -e "."            # CLI, API server, ComfyUI bridge
uv pip install -e ".[app]"       # + desktop window
uv pip install -e ".[local]"     # + on-device MusicGen (large: PyTorch)
uv pip install -e ".[lyria]"     # + Google Lyria

soundcraft doctor                # what is configured, what is missing
```

The core install is intentionally small — no PyTorch, no GUI toolkit — so it
fits on a headless server.

## Set up a backend

Use Settings in the app, or the command line:

```bash
# ComfyUI — see docs/comfyui.md
soundcraft config set COMFYUI_URL http://127.0.0.1:8188
soundcraft config set COMFYUI_WORKFLOW my-workflow.json

# Hosted backends
soundcraft config set REPLICATE_API_TOKEN r8_…
soundcraft config set HF_API_TOKEN hf_…
soundcraft config set GEMINI_API_KEY AIza…

soundcraft config list
soundcraft doctor
```

Settings are stored per user (`~/Library/Application Support/soundcraft/.env`
on macOS, `~/.config/soundcraft/.env` on Linux, `%APPDATA%\soundcraft\.env` on
Windows), or read from a project `.env` — see `.env.example`.

## Run it

| Need | Command |
|------|---------|
| Desktop window | `soundcraft app` |
| Browser GUI | `soundcraft gui` |
| API only | `soundcraft serve` |
| One-shot | `soundcraft "暗い、鼓動、インスタレーション"` |

## CLI

```bash
soundcraft "dark ambient drone, heavy reverb" --raw
soundcraft "glitch, metallic" -b comfyui -p duration=45 -p seed=1234
soundcraft "bright pop hook" -b lyria -n 3
soundcraft providers -v          # every backend and its parameters
```

| Flag | Description | Default |
|------|-------------|---------|
| `-b` | Backend id | first configured |
| `-p` | `name=value` backend parameter, repeatable | provider defaults |
| `-d` | Shorthand for `-p duration=…` | — |
| `-m` | Shorthand for `-p model=…` | — |
| `-n` | Number of variations | `1` |
| `-o` | Output directory | `output/`, or `~/Documents/soundcraft/output` in the app |
| `--raw` | Skip LLM prompt refinement | off |

Parameters differ per backend because the models do — `soundcraft providers -v`
prints exactly what the chosen one accepts.

## Local API

Same process as the GUI and desktop app. Default `http://127.0.0.1:8765`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness (never authenticated) |
| `GET` | `/providers` | Backends, parameters, readiness |
| `GET` `PUT` | `/settings` | Read / write settings |
| `POST` | `/generate` | Synchronous generation |
| `POST` | `/jobs` | Async generation — best for TouchDesigner |
| `GET` | `/jobs/{id}` | Poll a job |
| `GET` `DELETE` | `/library` | List / remove generated tracks |
| `GET` | `/media?path=` | Stream a file |
| `POST` | `/refine` | Preview prompt refinement |

```bash
curl -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"暗い、鼓動","backend":"comfyui","params":{"duration":30},"count":1}'
```

`files` in the response are absolute paths — load them in TouchDesigner with
`Audio File In CHOP`.

### Exposing it beyond localhost

The server refuses to bind a non-loopback address without a token:

```bash
soundcraft config set SOUNDCRAFT_API_TOKEN "$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
soundcraft serve --host 0.0.0.0
```

Clients then send `Authorization: Bearer <token>`. Set
`SOUNDCRAFT_CORS_ORIGINS` if a browser page on another host needs to call it.

## Output

```
~/Documents/soundcraft/output/…   # desktop app
./output/…                        # CLI / serve from a project folder
```

Each audio file gets a JSON sidecar with the prompt and settings it was made
with, which is what the Library reads. Set `SOUNDCRAFT_OUTPUT_DIR` to point
somewhere else.

## Development

```bash
uv pip install -e ".[dev,app,lyria]"
pytest
ruff check src tests
python scripts/build_app.py       # desktop bundle for this platform
```

Adding a backend means one file in `src/soundcraft/providers/` — declare its
parameters and settings, implement `generate()`, and the CLI, API and GUI pick
it up. See `docs/comfyui.md` for how the ComfyUI bridge maps a workflow.

## Requirements

- Python 3.10+ (or a desktop build)
- At least one configured backend — `soundcraft doctor` will tell you
- LM Studio, or any OpenAI-compatible endpoint, for prompt refinement (optional)
