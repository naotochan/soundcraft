from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from dotenv import dotenv_values

from soundcraft import settings
from soundcraft.naming import reserve_path
from soundcraft.paths import app_env_path


class TestPersistence:
    def test_round_trips_a_value(self):
        settings.save({"COMFYUI_URL": "http://gpu.local:8188"})
        assert settings.get("COMFYUI_URL") == "http://gpu.local:8188"

    def test_rejects_an_unknown_key(self):
        with pytest.raises(ValueError, match="Unknown setting"):
            settings.save({"NOT_A_SETTING": "x"})

    def test_empty_string_clears_a_setting_that_has_a_default(self):
        """Otherwise there is no way to turn prompt refinement off."""
        settings.save({"LM_STUDIO_MODEL": ""})
        assert settings.get("LM_STUDIO_MODEL") == ""

    def test_absent_variable_still_falls_back_to_the_default(self):
        assert settings.get("LM_STUDIO_URL") == "http://localhost:1234"


class TestValueSafety:
    def test_a_value_cannot_inject_another_key(self):
        with pytest.raises(ValueError, match="line break"):
            settings.save({"LM_STUDIO_MODEL": "m\nSOUNDCRAFT_OUTPUT_DIR=/etc"})
        assert os.getenv("SOUNDCRAFT_OUTPUT_DIR", "").endswith("output")

    def test_a_dollar_sign_survives_a_later_save(self):
        """Values are quoted and read without interpolation, so `$HOME` in a
        token is not expanded into a path."""
        token = "pa$$${HOME}word"
        settings.save({"SOUNDCRAFT_API_TOKEN": token})
        settings.save({"LM_STUDIO_MODEL": "unrelated"})
        assert dotenv_values(app_env_path(), interpolate=False)["SOUNDCRAFT_API_TOKEN"] == token

    def test_a_hash_is_not_treated_as_a_comment(self):
        url = "https://example.com/#anchor"
        settings.save({"LM_STUDIO_URL": url})
        assert dotenv_values(app_env_path(), interpolate=False)["LM_STUDIO_URL"] == url

    def test_shell_credentials_are_not_persisted(self, monkeypatch):
        """A token exported in a shell was meant for that session; saving an
        unrelated setting must not write it to disk."""
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_from_the_shell")
        settings.save({"LM_STUDIO_MODEL": "something"})
        on_disk = dotenv_values(app_env_path(), interpolate=False)
        assert "REPLICATE_API_TOKEN" not in on_disk

    def test_the_settings_file_is_owner_only(self):
        settings.save({"SOUNDCRAFT_API_TOKEN": "secret"})
        assert app_env_path().stat().st_mode & 0o077 == 0

    def test_unrecognised_keys_on_disk_survive_a_save(self):
        path = app_env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('FUTURE_SETTING="keep me"\n', encoding="utf-8")
        settings.save({"LM_STUDIO_MODEL": "x"})
        assert dotenv_values(path, interpolate=False)["FUTURE_SETTING"] == "keep me"


class TestConcurrency:
    def test_concurrent_saves_do_not_lose_each_other(self):
        keys = ["COMFYUI_URL", "LM_STUDIO_URL", "LM_STUDIO_MODEL", "HF_INFERENCE_BASE"]
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            list(pool.map(lambda k: settings.save({k: f"value-for-{k}"}), keys))

        on_disk = dotenv_values(app_env_path(), interpolate=False)
        assert all(on_disk[key] == f"value-for-{key}" for key in keys)

    def test_reserve_path_never_hands_out_the_same_name_twice(self, output_dir: Path):
        """Checking exists() and writing later lets a second generation
        overwrite the first."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            paths = list(pool.map(
                lambda _: reserve_path(output_dir, "dark ambient", ".wav"), range(8)
            ))
        assert len({p.name for p in paths}) == 8
