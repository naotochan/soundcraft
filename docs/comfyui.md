# Using soundcraft with ComfyUI

soundcraft does not ship a music model of its own for ComfyUI. It runs **your**
workflow. Anything ComfyUI can generate — ACE-Step, Stable Audio, MusicGen, or
whatever lands next month — works without changing soundcraft.

## 1. Build a working audio workflow in ComfyUI

Start from a template that already generates audio and make sure it runs
end-to-end in the ComfyUI web UI. It must finish in a **SaveAudio** node —
that is what soundcraft reads the result from.

## 2. Export it in API format

In ComfyUI: **Workflow → Export (API)**.

The plain "Export" produces a different file (it has a `nodes` array) that the
bridge cannot drive. soundcraft detects that case and tells you to re-export.

## 3. Drop the JSON into the workflows folder

```bash
soundcraft doctor        # prints the exact path
```

- macOS — `~/Library/Application Support/soundcraft/workflows/`
- Linux — `~/.config/soundcraft/workflows/`
- Windows — `%APPDATA%\soundcraft\workflows\`

Every `.json` in that folder appears in the **Workflow** dropdown.

## 4. Point soundcraft at ComfyUI

In Settings, or from the command line:

```bash
soundcraft config set COMFYUI_URL http://127.0.0.1:8188
soundcraft config set COMFYUI_WORKFLOW my-ace-step.json
soundcraft doctor
```

A ComfyUI on another machine works the same way — use its address. If it sits
behind a reverse proxy that wants a bearer token, set `COMFYUI_API_KEY`.

## How prompt, seed and duration get in

Before each run the bridge patches a copy of your workflow. It never edits the
file on disk, and it never overwrites an input that is wired to another node.

### Explicit (recommended)

Rename a node's title so it contains one of these markers:

| Marker | Patches |
|--------|---------|
| `soundcraft:prompt` | the prompt text |
| `soundcraft:negative` | the negative prompt |
| `soundcraft:seed` | the seed |
| `soundcraft:duration` | the clip length in seconds |

In ComfyUI: right-click the node → **Title** → e.g. `soundcraft:prompt`.
This is unambiguous and survives you rearranging the graph.

### Inferred (fallback)

Without markers, the bridge patches the first node with a conventional input
name:

- prompt — `text`, `prompt`, `tags`, `positive_prompt`
- seed — `seed`, `noise_seed`
- duration — `seconds`, `duration`, `seconds_total`, `length`, `audio_length`

Nodes whose title or class mentions "negative" are skipped when placing the
positive prompt, and receive the negative prompt instead.

If your graph has two text encoders and the wrong one gets the prompt, add the
markers — that is exactly what they are for.

## Troubleshooting

| Message | Cause |
|---------|-------|
| "looks like a UI export" | Re-export with **Export (API)** |
| "Could not find a text input" | Add a `soundcraft:prompt` title |
| "produced no audio file" | The workflow needs a SaveAudio node |
| "did not finish within …" | Raise `COMFYUI_TIMEOUT` in Settings |
| "Could not reach ComfyUI" | Wrong `COMFYUI_URL`, or ComfyUI is not running |
