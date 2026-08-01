from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from soundcraft.server import app


@pytest.fixture
def client(registered_fake) -> TestClient:
    return TestClient(app)


class TestHealth:
    def test_health_needs_no_auth(self, client, monkeypatch):
        monkeypatch.setenv("SOUNDCRAFT_API_TOKEN", "secret")
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["auth_required"] is True


class TestAuth:
    def test_open_when_no_token_is_configured(self, client):
        assert client.get("/providers").status_code == 200

    def test_rejects_a_missing_token(self, client, monkeypatch):
        monkeypatch.setenv("SOUNDCRAFT_API_TOKEN", "secret")
        assert client.get("/providers").status_code == 401

    def test_rejects_a_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("SOUNDCRAFT_API_TOKEN", "secret")
        resp = client.get("/providers", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_accepts_the_right_token(self, client, monkeypatch):
        monkeypatch.setenv("SOUNDCRAFT_API_TOKEN", "secret")
        resp = client.get("/providers", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200


class TestProviders:
    def test_describes_every_backend(self, client):
        body = client.get("/providers").json()
        ids = {p["id"] for p in body["providers"]}
        assert {"comfyui", "local", "replicate", "huggingface", "lyria"} <= ids
        assert body["default"]

    def test_each_backend_carries_the_metadata_the_ui_needs(self, client):
        for provider in client.get("/providers").json()["providers"]:
            assert provider["label"]
            assert "ready" in provider["status"]
            for param in provider["params"]:
                assert param["name"] and param["type"]


class TestGenerate:
    def test_generates_synchronously(self, client, output_dir: Path):
        resp = client.post(
            "/generate",
            json={"prompt": "dark drone", "backend": "fake", "raw": True, "count": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["files"]) == 2
        assert body["backend"] == "fake"
        assert all(Path(f).is_file() for f in body["files"])

    def test_rejects_an_empty_prompt(self, client):
        assert client.post("/generate", json={"prompt": ""}).status_code == 422

    def test_rejects_an_unknown_backend(self, client):
        resp = client.post("/generate", json={"prompt": "x", "backend": "nope"})
        assert resp.status_code == 400
        assert "Available" in resp.json()["detail"]

    def test_rejects_an_unknown_param(self, client):
        resp = client.post(
            "/generate",
            json={"prompt": "x", "backend": "fake", "raw": True, "params": {"tempo": 1}},
        )
        assert resp.status_code == 400
        assert "unknown parameter" in resp.json()["detail"]

    def test_explains_an_unconfigured_backend(self, client):
        resp = client.post("/generate", json={"prompt": "x", "backend": "huggingface"})
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"].lower()


class TestJobs:
    def test_job_runs_to_completion(self, client):
        created = client.post(
            "/jobs", json={"prompt": "x", "backend": "fake", "raw": True}
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        for _ in range(200):
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] in ("succeeded", "failed"):
                break
        assert job["status"] == "succeeded", job.get("error")
        assert len(job["result"]["files"]) == 1

    def test_failure_is_reported_on_the_job(self, client, registered_fake, monkeypatch):
        def explode(_request):
            raise RuntimeError("gpu melted")

        monkeypatch.setattr(registered_fake, "generate", explode)
        job_id = client.post(
            "/jobs", json={"prompt": "x", "backend": "fake", "raw": True}
        ).json()["id"]

        for _ in range(200):
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] in ("succeeded", "failed"):
                break
        assert job["status"] == "failed"
        assert "gpu melted" in job["error"]

    def test_missing_job_is_a_404(self, client):
        assert client.get("/jobs/deadbeef").status_code == 404


class TestMedia:
    def test_serves_a_generated_file(self, client, output_dir: Path):
        files = client.post(
            "/generate", json={"prompt": "x", "backend": "fake", "raw": True}
        ).json()["files"]
        resp = client.get("/media", params={"path": files[0]})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("audio/")

    def test_refuses_a_path_outside_the_library(self, client, isolated_env: Path):
        secret = isolated_env / "home" / ".ssh_id"
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.write_text("private", encoding="utf-8")
        assert client.get("/media", params={"path": str(secret)}).status_code == 403

    def test_refuses_traversal_out_of_the_library(self, client, output_dir: Path):
        resp = client.get("/media", params={"path": str(output_dir / ".." / "escape.wav")})
        assert resp.status_code == 403


class TestSettings:
    def test_never_returns_a_secret_in_the_clear(self, client, monkeypatch):
        monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_supersecretvalue")
        body = client.get("/settings").json()
        assert "r8_supersecretvalue" not in str(body)
        assert body["values"]["REPLICATE_API_TOKEN"]["set"] is True

    def test_schema_describes_every_setting(self, client):
        body = client.get("/settings").json()
        keys = {s["key"] for s in body["schema"]}
        assert {"REPLICATE_API_TOKEN", "COMFYUI_URL", "SOUNDCRAFT_API_TOKEN"} <= keys
        assert set(body["values"]) == keys

    def test_saving_persists_and_round_trips(self, client):
        resp = client.put("/settings", json={"COMFYUI_URL": "http://gpu.local:8188"})
        assert resp.status_code == 200
        assert resp.json()["values"]["COMFYUI_URL"]["value"] == "http://gpu.local:8188"
        assert client.get("/settings").json()["values"]["COMFYUI_URL"]["value"] == (
            "http://gpu.local:8188"
        )

    def test_omitted_keys_keep_their_value(self, client):
        client.put("/settings", json={"COMFYUI_URL": "http://a:8188"})
        client.put("/settings", json={"LM_STUDIO_MODEL": "some/model"})
        values = client.get("/settings").json()["values"]
        assert values["COMFYUI_URL"]["value"] == "http://a:8188"

    def test_empty_string_clears_a_secret(self, client):
        client.put("/settings", json={"REPLICATE_API_TOKEN": "r8_abc123456789"})
        assert client.get("/settings").json()["values"]["REPLICATE_API_TOKEN"]["set"]
        client.put("/settings", json={"REPLICATE_API_TOKEN": ""})
        assert not client.get("/settings").json()["values"]["REPLICATE_API_TOKEN"]["set"]

    def test_rejects_an_unknown_key(self, client):
        resp = client.put("/settings", json={"NOT_A_SETTING": "x"})
        assert resp.status_code == 400


class TestLibraryRoutes:
    def test_lists_generated_tracks(self, client, output_dir: Path):
        client.post("/generate", json={"prompt": "x", "backend": "fake", "raw": True})
        body = client.get("/library").json()
        assert body["count"] == 1
        assert body["tracks"][0]["backend"] == "fake"

    def test_deletes_a_track(self, client, output_dir: Path):
        path = client.post(
            "/generate", json={"prompt": "x", "backend": "fake", "raw": True}
        ).json()["files"][0]
        assert client.request("DELETE", "/library", params={"path": path}).status_code == 200
        assert client.get("/library").json()["count"] == 0

    def test_refuses_to_delete_outside_the_library(self, client, isolated_env: Path):
        outside = isolated_env / "precious.wav"
        outside.write_bytes(b"RIFF")
        resp = client.request("DELETE", "/library", params={"path": str(outside)})
        assert resp.status_code == 403
        assert outside.exists()
