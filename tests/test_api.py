import time
from dataclasses import replace

from fastapi.testclient import TestClient

import server.main as main_module
from server.ingest import is_text_path
from server.settings import settings as base_settings


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "settings", replace(base_settings, data_dir=tmp_path))
    return TestClient(main_module.app)


def wait_for_run(http, run_id):
    state = None
    for _ in range(200):
        state = http.get(f"/api/runs/{run_id}").json()
        if state["status"] in {"completed", "failed"}:
            return state
        time.sleep(0.025)
    raise AssertionError(f"run did not finish: {state}")


def test_mock_run_api_and_event_replay(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as http:
        assert http.get("/api/health").json()["status"] == "ok"
        response = http.post("/api/runs", data={"brief": "A local planning studio", "output_format": "both", "loop_counts": '{"ideation":1,"architecture":1,"workpackage":1}'}, files={"files": ("notes.md", b"# useful context", "text/markdown")})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        state = wait_for_run(http, run_id)
        assert state["status"] == "completed", state
        assert state["tokens"]["total"] > 0
        assert len(state["outputs"]) == 8
        output = http.get(f"/api/runs/{run_id}/outputs/L3_workpackage?format=json")
        assert output.status_code == 200
        assert output.json()["canonical_output"]["tasks"][0]["id"] == "T-001"
        replay = http.get(f"/api/runs/{run_id}/events").text
        assert "event: tokens.updated" in replay
        assert "event: run.completed" in replay
        assert http.get(f"/api/runs/{run_id}/outputs/../../state?format=json").status_code == 404


def test_settings_and_write_only_keys(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as http:
        created = http.post("/api/keys", json={"provider": "openai", "label": "local OpenAI", "value": "super-secret-value"})
        assert created.status_code == 201
        key_id = created.json()["id"]
        listing = http.get("/api/keys").json()
        assert listing[0]["id"] == key_id
        assert "value" not in listing[0]
        assert "super-secret" not in str(listing)
        nodes = http.get("/api/settings/nodes").json()
        assert len(nodes) == 9
        updated = http.put(f"/api/settings/nodes/{nodes[0]['id']}", json={"provider": "openai", "model": "gpt-5-mini", "api_key_ref": key_id, "temperature": 0.3})
        assert updated.status_code == 200
        assert updated.json()["api_key_ref"] == key_id
        assert http.delete(f"/api/keys/{key_id}").status_code == 204


def test_gemini_and_deep_research_node_configuration(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as http:
        created = http.post(
            "/api/keys",
            json={"provider": "gemini", "label": "Gemini", "value": "secret"},
        )
        key_id = created.json()["id"]
        nodes = http.get("/api/settings/nodes").json()
        researcher = next(node for node in nodes if node["id"] == "researcher")
        assert researcher["mode"] == "standard"
        updated = http.put(
            "/api/settings/nodes/researcher",
            json={
                **{key: value for key, value in researcher.items() if key not in {"id", "role"}},
                "provider": "gemini",
                "model": "deep-research-preview-04-2026",
                "mode": "deep_research",
                "normalization_model": "gemini-2.5-flash",
                "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key_ref": key_id,
                "research_timeout_seconds": 1800,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["model"] == "deep-research-preview-04-2026"
        assert updated.json()["base_url"].endswith("/v1beta")

        non_researcher = next(node for node in nodes if node["id"] != "researcher")
        rejected = http.put(
            f"/api/settings/nodes/{non_researcher['id']}",
            json={
                "provider": "gemini",
                "model": "deep-research-preview-04-2026",
                "mode": "deep_research",
                "normalization_model": "gemini-2.5-flash",
            },
        )
        assert rejected.status_code == 422


def test_node_base_url_rejects_embedded_credentials(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as http:
        response = http.put(
            "/api/settings/nodes/intake",
            json={
                "provider": "openai",
                "model": "gpt-exact",
                "base_url": "https://secret@example.com/v1",
            },
        )
        assert response.status_code == 422


def test_intake_limits(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as http:
        response = http.post("/api/runs", data={"brief": "word " * 2001})
        assert response.status_code == 422
        bad_repo = http.post("/api/runs", data={"brief": "valid", "github_url": "https://example.com/repo"})
        assert bad_repo.status_code == 422


def test_repository_text_allowlist():
    assert is_text_path("README")
    assert is_text_path("docs/guide.md")
    assert is_text_path("Dockerfile")
    assert not is_text_path("assets/logo.png")
    assert not is_text_path(".env")
