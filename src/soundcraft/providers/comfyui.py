"""ComfyUI bridge — run any audio workflow the user already has.

Rather than hardcoding one model, this provider drives a user-supplied workflow
exported from ComfyUI in *API format* (Workflow → Export (API)). Whatever
ComfyUI can generate — ACE-Step, Stable Audio, MusicGen, anything added later —
becomes available without changing this file.

Prompt / seed / duration are injected into the workflow before submission:

1. **Explicit** — rename a node's title to contain ``soundcraft:prompt``,
   ``soundcraft:negative``, ``soundcraft:seed`` or ``soundcraft:duration``.
   This always wins and is the recommended setup.
2. **Inferred** — otherwise the bridge looks for conventional input names
   (``text``/``tags``/``prompt``, ``seed``/``noise_seed``,
   ``seconds``/``duration``) and patches the first match.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from soundcraft import settings
from soundcraft.paths import workflows_dir
from soundcraft.providers.base import (
    READY,
    Availability,
    GeneratedAudio,
    GenerationRequest,
    Option,
    ParamSpec,
    Provider,
    ProviderError,
    ProviderUnavailable,
    SettingSpec,
)
from soundcraft.providers.registry import register

MARKER = "soundcraft:"
PROMPT_KEYS = ("text", "prompt", "tags", "positive_prompt")
NEGATIVE_KEYS = ("text", "prompt", "negative_prompt")
SEED_KEYS = ("seed", "noise_seed")
DURATION_KEYS = ("seconds", "duration", "seconds_total", "length", "audio_length")

NEGATIVE_HINTS = ("negative", "neg_", "uncond")
AUDIO_SUFFIXES = (".flac", ".wav", ".mp3", ".ogg", ".m4a", ".opus")


def _titles(node: dict[str, Any]) -> str:
    meta = node.get("_meta") or {}
    return str(meta.get("title") or "").lower()


def _marked(node: dict[str, Any], name: str) -> bool:
    return f"{MARKER}{name}" in _titles(node)


def _looks_negative(node: dict[str, Any]) -> bool:
    haystack = _titles(node) + " " + str(node.get("class_type", "")).lower()
    return any(hint in haystack for hint in NEGATIVE_HINTS)


def _set_first(node: dict[str, Any], keys: tuple[str, ...], value: Any) -> bool:
    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return False
    for key in keys:
        if key in inputs and not isinstance(inputs[key], list):
            inputs[key] = value
            return True
    return False


class ComfyUIProvider(Provider):
    id = "comfyui"
    label = "ComfyUI"
    summary = (
        "Drive your own ComfyUI audio workflow. Any model ComfyUI supports "
        "(ACE-Step, Stable Audio, MusicGen, …) works with no code changes."
    )
    tags = ("self-hosted", "gpu", "any-model", "offline-capable")
    docs_url = "https://docs.comfy.org/"
    speed = "Depends on your workflow and GPU"

    settings = (
        SettingSpec(
            key="COMFYUI_URL",
            label="ComfyUI URL",
            default="http://127.0.0.1:8188",
            help="Base URL of a running ComfyUI instance (local or on the network).",
            placeholder="http://127.0.0.1:8188",
        ),
        SettingSpec(
            key="COMFYUI_WORKFLOW",
            label="Default workflow",
            help=(
                "Filename inside the workflows folder, or an absolute path to a "
                "workflow exported with Workflow → Export (API)."
            ),
            placeholder="ace-step.json",
        ),
        SettingSpec(
            key="COMFYUI_API_KEY",
            label="ComfyUI auth token",
            secret=True,
            help="Optional Bearer token, for a ComfyUI behind a reverse proxy.",
        ),
        SettingSpec(
            key="COMFYUI_TIMEOUT",
            label="ComfyUI timeout (s)",
            default="900",
            help="How long to wait for a queued job before giving up.",
        ),
    )

    params = (
        ParamSpec(
            name="workflow",
            label="Workflow",
            type="select",
            default="",
            help="Workflow to run. Defaults to the one set in Settings.",
            optional=True,
        ),
        ParamSpec(
            name="duration",
            label="Duration",
            type="number",
            default=30,
            minimum=1,
            maximum=600,
            step=1,
            unit="s",
            help="Injected only if the workflow exposes a duration input.",
        ),
        ParamSpec(
            name="seed",
            label="Seed",
            type="number",
            default=None,
            minimum=0,
            maximum=2**53 - 1,
            step=1,
            optional=True,
            help="Leave empty for a new random seed each run.",
        ),
        ParamSpec(
            name="negative_prompt",
            label="Negative prompt",
            type="text",
            default="",
            optional=True,
            help="Injected only if the workflow has a negative prompt node.",
        ),
    )

    # -- discovery -------------------------------------------------------

    def base_url(self) -> str:
        return settings.get("COMFYUI_URL").rstrip("/")

    def available_workflows(self) -> list[Path]:
        directory = workflows_dir()
        if not directory.is_dir():
            return []
        return sorted(p for p in directory.glob("*.json") if p.is_file())

    def describe(self) -> dict[str, Any]:
        """Fill the workflow dropdown from disk at request time."""
        described = super().describe()
        options = [Option(p.name, p.stem).as_dict() for p in self.available_workflows()]
        for param in described["params"]:
            if param["name"] == "workflow":
                param["options"] = options
                param["default"] = settings.get("COMFYUI_WORKFLOW")
        described["workflows_dir"] = str(workflows_dir())
        return described

    def availability(self) -> Availability:
        if not settings.get("COMFYUI_URL"):
            return Availability(
                False,
                "ComfyUI URL is not set.",
                "Add the URL of your ComfyUI instance in Settings.",
            )
        if not settings.get("COMFYUI_WORKFLOW") and not self.available_workflows():
            return Availability(
                False,
                "No workflow available.",
                f"Export a workflow with Workflow → Export (API) and drop the "
                f"JSON into {workflows_dir()}.",
            )
        return READY

    # -- workflow handling -----------------------------------------------

    def resolve_workflow(self, name: str | None) -> Path:
        chosen = (name or settings.get("COMFYUI_WORKFLOW")).strip()
        if not chosen:
            candidates = self.available_workflows()
            if not candidates:
                raise ProviderUnavailable(
                    "No ComfyUI workflow configured. Export one with "
                    f"Workflow → Export (API) into {workflows_dir()}."
                )
            return candidates[0]

        path = Path(chosen).expanduser()
        if not path.is_absolute():
            path = workflows_dir() / path
        if not path.is_file():
            raise ProviderUnavailable(f"Workflow not found: {path}")
        return path

    def load_workflow(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProviderError(f"Could not read workflow {path.name}: {e}") from e

        # ComfyUI's UI export nests the graph; the API export is already flat.
        if isinstance(data, dict) and "nodes" in data and "prompt" not in data:
            raise ProviderError(
                f"{path.name} looks like a UI export. Re-export it with "
                "Workflow → Export (API) — soundcraft needs the API format."
            )
        if isinstance(data, dict) and isinstance(data.get("prompt"), dict):
            data = data["prompt"]
        if not isinstance(data, dict) or not data:
            raise ProviderError(f"{path.name} is not a valid ComfyUI API workflow.")
        return data

    def inject(
        self,
        workflow: dict[str, Any],
        *,
        prompt: str,
        negative: str,
        seed: int,
        duration: int | None,
    ) -> dict[str, Any]:
        """Patch prompt/seed/duration into a copy of the workflow."""
        graph = json.loads(json.dumps(workflow))
        nodes = [(key, node) for key, node in graph.items() if isinstance(node, dict)]
        ordered = sorted(nodes, key=lambda kv: _node_sort_key(kv[0]))

        done = {"prompt": False, "negative": False, "seed": False, "duration": False}

        # Pass 1 — explicit soundcraft: markers.
        for _, node in ordered:
            if _marked(node, "prompt") and not done["prompt"]:
                done["prompt"] = _set_first(node, PROMPT_KEYS, prompt)
            if _marked(node, "negative") and not done["negative"]:
                done["negative"] = _set_first(node, NEGATIVE_KEYS, negative)
            if _marked(node, "seed") and not done["seed"]:
                done["seed"] = _set_first(node, SEED_KEYS, seed)
            if _marked(node, "duration") and not done["duration"] and duration:
                done["duration"] = _set_first(node, DURATION_KEYS, duration)

        # Pass 2 — infer from conventional input names.
        for _, node in ordered:
            negative_node = _looks_negative(node)
            if not done["prompt"] and not negative_node:
                done["prompt"] = _set_first(node, PROMPT_KEYS, prompt)
            elif not done["negative"] and negative_node and negative:
                done["negative"] = _set_first(node, NEGATIVE_KEYS, negative)
            if not done["seed"]:
                done["seed"] = _set_first(node, SEED_KEYS, seed)
            if not done["duration"] and duration:
                done["duration"] = _set_first(node, DURATION_KEYS, duration)

        if not done["prompt"]:
            raise ProviderError(
                "Could not find a text input to inject the prompt into. Rename the "
                "target node's title so it contains 'soundcraft:prompt'."
            )
        return graph

    # -- execution -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = settings.get("COMFYUI_API_KEY")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def generate(self, request: GenerationRequest) -> GeneratedAudio:
        base = self.base_url()
        if not base:
            raise ProviderUnavailable("ComfyUI URL is not set.")

        path = self.resolve_workflow(request.params.get("workflow"))
        workflow = self.load_workflow(path)
        seed = request.params.get("seed")
        seed = int(seed) if seed is not None else random.randrange(2**31)
        graph = self.inject(
            workflow,
            prompt=request.prompt,
            negative=str(request.get("negative_prompt", "")),
            seed=seed,
            duration=request.params.get("duration"),
        )

        client_id = uuid.uuid4().hex
        try:
            resp = requests.post(
                f"{base}/prompt",
                json={"prompt": graph, "client_id": client_id},
                headers=self._headers(),
                timeout=60,
            )
        except requests.RequestException as e:
            raise ProviderError(
                f"Could not reach ComfyUI at {base}. Is it running? ({e})"
            ) from e

        if resp.status_code >= 400:
            raise ProviderError(f"ComfyUI rejected the workflow: {_detail(resp)}")

        payload = resp.json()
        if payload.get("node_errors"):
            raise ProviderError(f"ComfyUI node errors: {payload['node_errors']}")
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise ProviderError("ComfyUI did not return a prompt id.")

        entry = self._wait_for_history(base, prompt_id)
        filename, subfolder, kind = self._first_audio_output(entry)
        data = self._download(base, filename, subfolder, kind)
        suffix = Path(filename).suffix.lower() or ".flac"
        return GeneratedAudio(
            data=data,
            suffix=suffix,
            extra={"seed": seed, "workflow": path.name},
        )

    def _timeout(self) -> float:
        try:
            return float(settings.get("COMFYUI_TIMEOUT"))
        except ValueError:
            return 900.0

    def _wait_for_history(self, base: str, prompt_id: str) -> dict[str, Any]:
        deadline = time.time() + self._timeout()
        delay = 0.5
        while time.time() < deadline:
            try:
                resp = requests.get(
                    f"{base}/history/{prompt_id}",
                    headers=self._headers(),
                    timeout=30,
                )
                resp.raise_for_status()
                history = resp.json()
            except requests.RequestException:
                history = {}

            entry = history.get(prompt_id) if isinstance(history, dict) else None
            if entry:
                status = (entry.get("status") or {}).get("status_str")
                if status == "error":
                    raise ProviderError(f"ComfyUI run failed: {_status_error(entry)}")
                if entry.get("outputs"):
                    return entry

            time.sleep(delay)
            delay = min(delay * 1.4, 3.0)

        raise ProviderError(
            f"ComfyUI did not finish within {self._timeout():.0f}s. "
            "Raise the timeout in Settings if your workflow is slow."
        )

    def _first_audio_output(self, entry: dict[str, Any]) -> tuple[str, str, str]:
        outputs = entry.get("outputs") or {}
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for key in ("audio", "audios", "images", "files"):
                for item in node_output.get(key) or []:
                    filename = (item or {}).get("filename", "")
                    if Path(filename).suffix.lower() in AUDIO_SUFFIXES:
                        return (
                            filename,
                            item.get("subfolder", ""),
                            item.get("type", "output"),
                        )
        raise ProviderError(
            "The workflow finished but produced no audio file. Make sure it ends "
            "in a SaveAudio node."
        )

    def _download(self, base: str, filename: str, subfolder: str, kind: str) -> bytes:
        try:
            resp = requests.get(
                f"{base}/view",
                params={"filename": filename, "subfolder": subfolder, "type": kind},
                headers=self._headers(),
                timeout=300,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ProviderError(f"Could not download {filename} from ComfyUI: {e}") from e
        if not resp.content:
            raise ProviderError(f"ComfyUI returned an empty file for {filename}.")
        return resp.content


def _node_sort_key(node_id: str) -> tuple[int, str]:
    """Numeric node ids sort numerically; anything else falls back to text."""
    return (int(node_id), "") if node_id.isdigit() else (2**31, node_id)


def _status_error(entry: dict[str, Any]) -> str:
    messages = (entry.get("status") or {}).get("messages") or []
    for name, payload in messages:
        if name == "execution_error" and isinstance(payload, dict):
            return str(payload.get("exception_message") or payload)
    return "unknown error"


def _detail(resp: requests.Response) -> str:
    try:
        return json.dumps(resp.json())[:500]
    except ValueError:
        return resp.text[:500]


register(ComfyUIProvider())
