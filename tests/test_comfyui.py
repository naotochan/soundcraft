from __future__ import annotations

import json

import pytest

from soundcraft.providers.base import ProviderError
from soundcraft.providers.comfyui import ComfyUIProvider

ACE_STEP_LIKE = {
    "3": {
        "class_type": "TextEncodeAceStepAudio",
        "inputs": {"tags": "placeholder tags", "lyrics": "", "lyrics_strength": 1.0},
    },
    "5": {
        "class_type": "EmptyAceStepLatentAudio",
        "inputs": {"seconds": 120.0, "batch_size": 1},
    },
    "6": {
        "class_type": "KSampler",
        "inputs": {"seed": 0, "steps": 50, "positive": ["3", 0], "latent_image": ["5", 0]},
    },
    "7": {"class_type": "SaveAudio", "inputs": {"audio": ["6", 0]}},
}


@pytest.fixture
def provider() -> ComfyUIProvider:
    return ComfyUIProvider()


class TestInjection:
    def test_infers_prompt_seed_and_duration(self, provider):
        graph = provider.inject(
            ACE_STEP_LIKE, prompt="dark drone", negative="", seed=42, duration=30
        )
        assert graph["3"]["inputs"]["tags"] == "dark drone"
        assert graph["6"]["inputs"]["seed"] == 42
        assert graph["5"]["inputs"]["seconds"] == 30

    def test_leaves_the_source_workflow_untouched(self, provider):
        before = json.dumps(ACE_STEP_LIKE, sort_keys=True)
        provider.inject(ACE_STEP_LIKE, prompt="x", negative="", seed=1, duration=5)
        assert json.dumps(ACE_STEP_LIKE, sort_keys=True) == before

    def test_explicit_marker_wins_over_inference(self, provider):
        workflow = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "decoy"}},
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "target"},
                "_meta": {"title": "soundcraft:prompt"},
            },
        }
        graph = provider.inject(workflow, prompt="chosen", negative="", seed=1, duration=None)
        assert graph["2"]["inputs"]["text"] == "chosen"
        assert graph["1"]["inputs"]["text"] == "decoy"

    def test_negative_node_does_not_receive_the_positive_prompt(self, provider):
        workflow = {
            "1": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": ""},
                "_meta": {"title": "Negative prompt"},
            },
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        }
        graph = provider.inject(
            workflow, prompt="positive", negative="muddy", seed=1, duration=None
        )
        assert graph["2"]["inputs"]["text"] == "positive"
        assert graph["1"]["inputs"]["text"] == "muddy"

    def test_never_overwrites_a_node_link(self, provider):
        """Inputs wired to another node are lists and must stay wired."""
        workflow = {
            "1": {"class_type": "Sampler", "inputs": {"text": ["2", 0]}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        }
        graph = provider.inject(workflow, prompt="hello", negative="", seed=1, duration=None)
        assert graph["1"]["inputs"]["text"] == ["2", 0]
        assert graph["2"]["inputs"]["text"] == "hello"

    def test_reports_clearly_when_no_text_input_exists(self, provider):
        with pytest.raises(ProviderError, match="soundcraft:prompt"):
            provider.inject(
                {"1": {"class_type": "SaveAudio", "inputs": {"audio": ["2", 0]}}},
                prompt="x",
                negative="",
                seed=1,
                duration=None,
            )

    def test_nodes_are_visited_in_numeric_order(self, provider):
        """Node ids are strings, so "10" must not sort before "2"."""
        workflow = {
            "10": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        }
        graph = provider.inject(workflow, prompt="first", negative="", seed=1, duration=None)
        assert graph["2"]["inputs"]["text"] == "first"
        assert graph["10"]["inputs"]["text"] == ""


class TestWorkflowLoading:
    def test_rejects_a_ui_export_with_a_useful_message(self, provider, tmp_path):
        path = tmp_path / "ui.json"
        path.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
        with pytest.raises(ProviderError, match="Export \\(API\\)"):
            provider.load_workflow(path)

    def test_unwraps_a_prompt_wrapper(self, provider, tmp_path):
        path = tmp_path / "wrapped.json"
        path.write_text(json.dumps({"prompt": ACE_STEP_LIKE}), encoding="utf-8")
        assert provider.load_workflow(path)["3"]["class_type"] == "TextEncodeAceStepAudio"

    def test_rejects_malformed_json(self, provider, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ProviderError, match="Could not read"):
            provider.load_workflow(path)


class TestOutputSelection:
    def test_picks_the_first_audio_file(self, provider):
        entry = {
            "outputs": {
                "9": {"images": [{"filename": "preview.png", "type": "output"}]},
                "7": {"audio": [{"filename": "out.flac", "subfolder": "a", "type": "output"}]},
            }
        }
        assert provider._first_audio_output(entry) == ("out.flac", "a", "output")

    def test_explains_a_workflow_that_saves_no_audio(self, provider):
        entry = {"outputs": {"9": {"images": [{"filename": "preview.png"}]}}}
        with pytest.raises(ProviderError, match="SaveAudio"):
            provider._first_audio_output(entry)
