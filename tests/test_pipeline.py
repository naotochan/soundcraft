from __future__ import annotations

import json
from pathlib import Path

import pytest

from soundcraft.library import list_tracks, track_from_file
from soundcraft.naming import next_sequence, prompt_to_slug, reserve_path
from soundcraft.pipeline import run_generate


class TestNaming:
    def test_slug_uses_the_first_few_words(self):
        assert prompt_to_slug("Dark ambient drone with heavy reverb") == "dark_ambient_drone_with"

    def test_slug_falls_back_when_nothing_is_usable(self):
        assert prompt_to_slug("暗い、鼓動") == "generated"
        assert prompt_to_slug("") == "generated"

    def test_slug_is_length_capped(self):
        assert len(prompt_to_slug("supercalifragilistic " * 5)) <= 48

    def test_sequence_continues_past_existing_files(self, output_dir: Path):
        (output_dir / "dark_001.wav").write_bytes(b"")
        (output_dir / "dark_007.mp3").write_bytes(b"")
        assert next_sequence(output_dir, "dark") == 8

    def test_reserve_path_skips_an_occupied_slot(self, output_dir: Path):
        (output_dir / "dark_001.wav").write_bytes(b"")
        # A .flac sibling does not bump the counter, so 001 is contested.
        (output_dir / "dark_002.flac").write_bytes(b"")
        assert reserve_path(output_dir, "dark", ".flac").name == "dark_003.flac"


class TestRunGenerate:
    def test_writes_one_file_per_variation(self, registered_fake, output_dir: Path):
        result = run_generate(
            "dark drone", backend="fake", count=3, output_dir=output_dir, raw=True
        )
        assert len(result.files) == 3
        assert len({p.name for p in result.files}) == 3
        assert all(p.read_bytes() == b"RIFFfake" for p in result.files)

    def test_writes_a_sidecar_that_records_the_run(self, registered_fake, output_dir: Path):
        result = run_generate(
            "dark drone",
            backend="fake",
            params={"duration": 20},
            output_dir=output_dir,
            raw=True,
        )
        meta = json.loads(result.files[0].with_suffix(".json").read_text(encoding="utf-8"))
        assert meta["backend"] == "fake"
        assert meta["prompt"] == "dark drone"
        assert meta["params"]["duration"] == 20

    def test_refines_the_prompt_once_for_the_whole_batch(
        self, registered_fake, output_dir: Path, monkeypatch
    ):
        calls = []

        def fake_refine(text: str) -> str:
            calls.append(text)
            return "refined " + text

        monkeypatch.setattr("soundcraft.pipeline.refine_prompt", fake_refine)
        result = run_generate("seed", backend="fake", count=3, output_dir=output_dir)

        assert calls == ["seed"]
        assert result.prompt == "refined seed"
        assert result.input == "seed"

    def test_raw_skips_refinement(self, registered_fake, output_dir: Path, monkeypatch):
        monkeypatch.setattr(
            "soundcraft.pipeline.refine_prompt",
            lambda _: pytest.fail("refine_prompt should not run with raw=True"),
        )
        run_generate("as typed", backend="fake", output_dir=output_dir, raw=True)

    def test_invalid_params_fail_before_any_file_is_written(
        self, registered_fake, output_dir: Path
    ):
        with pytest.raises(ValueError):
            run_generate("x", backend="fake", params={"duration": 9999}, output_dir=output_dir)
        assert list(output_dir.iterdir()) == []

    def test_progress_reports_each_completed_clip(self, registered_fake, output_dir: Path):
        seen = []
        run_generate(
            "x",
            backend="fake",
            count=2,
            output_dir=output_dir,
            raw=True,
            progress=lambda done, total, path: seen.append((done, total)),
        )
        assert seen == [(1, 2), (2, 2)]

    def test_creates_a_missing_output_directory(self, registered_fake, isolated_env: Path):
        target = isolated_env / "nested" / "deeper"
        result = run_generate("x", backend="fake", output_dir=target, raw=True)
        assert result.files[0].parent == target.resolve()


class TestLibrary:
    def test_track_reads_back_what_the_pipeline_wrote(
        self, registered_fake, output_dir: Path
    ):
        result = run_generate(
            "dark drone", backend="fake", params={"model": "b"}, output_dir=output_dir, raw=True
        )
        track = track_from_file(result.files[0])
        assert track["backend"] == "fake"
        assert track["prompt"] == "dark drone"
        assert track["params"]["model"] == "b"
        assert track["has_meta"] is True

    def test_track_without_a_sidecar_still_lists(self, output_dir: Path):
        orphan = output_dir / "hand_placed_001.wav"
        orphan.write_bytes(b"RIFF")
        track = track_from_file(orphan)
        assert track["has_meta"] is False
        assert track["title"] == "hand placed"

    def test_listing_is_newest_first(self, registered_fake, output_dir: Path):
        run_generate("first", backend="fake", output_dir=output_dir, raw=True)
        run_generate("second", backend="fake", output_dir=output_dir, raw=True)
        tracks = list_tracks()
        assert [t["prompt"] for t in tracks][:2] == ["second", "first"]

    def test_listing_can_filter_by_backend(self, registered_fake, output_dir: Path):
        run_generate("x", backend="fake", output_dir=output_dir, raw=True)
        assert list_tracks(backend="fake")
        assert list_tracks(backend="nothing-here") == []

    def test_flac_output_is_recognised(self, output_dir: Path):
        (output_dir / "comfy_001.flac").write_bytes(b"fLaC")
        assert [t["format"] for t in list_tracks()] == ["flac"]

    def test_limit_is_applied_before_sidecars_are_read(
        self, registered_fake, output_dir: Path, monkeypatch
    ):
        for i in range(5):
            run_generate(f"take {i}", backend="fake", output_dir=output_dir, raw=True)

        import soundcraft.library as library

        read: list[Path] = []
        original = library._read_meta

        def spy(audio: Path):
            read.append(audio)
            return original(audio)

        monkeypatch.setattr(library, "_read_meta", spy)
        tracks = library.list_tracks(limit=2)
        assert len(tracks) == 2
        assert len(read) == 2


class TestDeletion:
    def test_deletes_the_audio_and_its_sidecar(self, registered_fake, output_dir: Path):
        from soundcraft.library import delete_track

        result = run_generate("x", backend="fake", output_dir=output_dir, raw=True)
        audio = result.files[0]
        delete_track(audio)
        assert not audio.exists()
        assert not audio.with_suffix(".json").exists()

    def test_refuses_a_path_outside_the_library(self, isolated_env: Path):
        from soundcraft.library import delete_track

        outside = isolated_env / "precious.wav"
        outside.write_bytes(b"RIFF")
        with pytest.raises(ValueError, match="Refusing to delete"):
            delete_track(outside)
        assert outside.exists()
