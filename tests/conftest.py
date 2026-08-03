from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep every test away from the developer's real settings and output."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("SOUNDCRAFT_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.delenv("SOUNDCRAFT_APP", raising=False)

    for key in (
        "REPLICATE_API_TOKEN",
        "GEMINI_API_KEY",
        "HF_API_TOKEN",
        "COMFYUI_URL",
        "COMFYUI_WORKFLOW",
        "COMFYUI_API_KEY",
        "REPLICATE_MODELS",
        "SOUNDCRAFT_API_TOKEN",
        "SOUNDCRAFT_CORS_ORIGINS",
        "LM_STUDIO_URL",
        "LM_STUDIO_MODEL",
        "LOCAL_DEVICE",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def output_dir(isolated_env: Path) -> Path:
    path = isolated_env / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def fake_provider():
    """A provider that returns fixed bytes, so pipeline tests never hit a network."""
    from soundcraft.providers.base import (
        GeneratedAudio,
        GenerationRequest,
        Option,
        ParamSpec,
        Provider,
    )

    class FakeProvider(Provider):
        id = "fake"
        label = "Fake"
        summary = "Test double"
        params = (
            ParamSpec("duration", "Duration", "number", default=10, minimum=1, maximum=60),
            ParamSpec(
                "model",
                "Model",
                "select",
                default="a",
                options=(Option("a", "A"), Option("b", "B")),
            ),
            ParamSpec("seed", "Seed", "number", default=None, minimum=0, optional=True),
        )

        def __init__(self) -> None:
            self.calls: list[GenerationRequest] = []

        def generate(self, request: GenerationRequest) -> GeneratedAudio:
            self.calls.append(request)
            return GeneratedAudio(data=b"RIFFfake", suffix=".wav", extra={"n": len(self.calls)})

    return FakeProvider()


@pytest.fixture
def registered_fake(fake_provider, monkeypatch: pytest.MonkeyPatch):
    """Register the fake provider for the duration of one test."""
    from soundcraft.providers import registry

    registry._ensure_loaded()
    monkeypatch.setitem(registry._providers, fake_provider.id, fake_provider)
    monkeypatch.setattr(registry, "_order", [fake_provider.id, *registry._order])
    return fake_provider
