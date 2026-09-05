"""Mission Control / Current Focus — HTTP-level tests. Uses the standard
`client` fixture (fake Hermes/STT/TTS already wired by conftest.py) — no
real Google/Keychain/Hermes/model call, and no model call is ever expected
from any of these endpoints (candidates/start/pause/resume/complete/
abandon/history are all pure local reads/writes)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_life_task(client: TestClient, title: str = "Renew passport") -> str:
    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": title, "due_date": "2020-01-01"}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_candidates_endpoint_returns_empty_shape_with_no_data(client: TestClient) -> None:
    resp = client.get("/api/mission-control/candidates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended"] is None
    assert body["alternatives"] == []
    assert body["watch"] == []
    assert "generated_at" in body


def test_candidates_endpoint_surfaces_a_real_life_task(client: TestClient) -> None:
    _create_life_task(client, title="Renew passport")
    resp = client.get("/api/mission-control/candidates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended"] is not None
    assert body["recommended"]["source_type"] == "life_task"
    assert body["recommended"]["domain_slug"] == "life"


def test_current_mission_is_null_when_none_started(client: TestClient) -> None:
    resp = client.get("/api/mission-control/current")
    assert resp.status_code == 200
    assert resp.json()["session"] is None


def test_start_mission_from_a_real_source_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    resp = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task_id, "target_duration_minutes": 25},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["domain_slug"] == "life"
    assert body["target_duration_minutes"] == 25
    assert body["elapsed_seconds"] == 0

    current = client.get("/api/mission-control/current").json()
    assert current["session"]["id"] == body["id"]


def test_start_manual_mission_over_http(client: TestClient) -> None:
    resp = client.post(
        "/api/mission-control/sessions",
        json={
            "source_type": "manual",
            "title": "Write project notes",
            "domain_slug": "build",
            "target_duration_minutes": 45,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Write project notes"
    assert body["domain_slug"] == "build"
    assert body["source_type"] == "manual"


def test_start_mission_rejects_bad_source_reference_with_400(client: TestClient) -> None:
    resp = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": "does-not-exist", "target_duration_minutes": 25},
    )
    assert resp.status_code == 400


def test_start_mission_rejects_unrecognized_source_type_with_422(client: TestClient) -> None:
    resp = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "mind_checkin", "source_id": "x", "target_duration_minutes": 25},
    )
    assert resp.status_code == 422  # rejected by the Pydantic Literal before it reaches the service


def test_start_mission_rejects_out_of_range_duration_with_422(client: TestClient) -> None:
    task_id = _create_life_task(client)
    resp = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task_id, "target_duration_minutes": 500},
    )
    assert resp.status_code == 422


def test_second_start_while_one_is_active_returns_400(client: TestClient) -> None:
    task1 = _create_life_task(client, "Task A")
    task2 = _create_life_task(client, "Task B")
    resp1 = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task1, "target_duration_minutes": 25},
    )
    assert resp1.status_code == 201
    resp2 = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task2, "target_duration_minutes": 25},
    )
    assert resp2.status_code == 400


def test_full_lifecycle_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    started = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task_id, "target_duration_minutes": 25},
    ).json()
    session_id = started["id"]

    paused = client.post(f"/api/mission-control/sessions/{session_id}/pause", json={})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.post(f"/api/mission-control/sessions/{session_id}/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    completed = client.post(
        f"/api/mission-control/sessions/{session_id}/complete",
        json={"completion_note": "Filed the renewal form", "what_changed_note": "Passport application submitted"},
    )
    assert completed.status_code == 200
    body = completed.json()
    assert body["status"] == "completed"
    assert body["completion_note"] == "Filed the renewal form"

    # No longer the current mission.
    assert client.get("/api/mission-control/current").json()["session"] is None

    history = client.get("/api/mission-control/history").json()
    assert len(history) == 1
    assert history[0]["id"] == session_id


def test_abandon_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    started = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task_id, "target_duration_minutes": 25},
    ).json()
    resp = client.post(f"/api/mission-control/sessions/{started['id']}/abandon", json={"completion_note": "Got interrupted"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "abandoned"


def test_pause_unknown_session_returns_400(client: TestClient) -> None:
    resp = client.post("/api/mission-control/sessions/does-not-exist/pause", json={})
    assert resp.status_code == 400


def test_completing_a_mission_never_mutates_the_underlying_life_task(client: TestClient) -> None:
    task_id = _create_life_task(client, title="Renew passport")
    before = client.get("/api/domains/life/records").json()
    started = client.post(
        "/api/mission-control/sessions",
        json={"source_type": "life_task", "source_id": task_id, "target_duration_minutes": 25},
    ).json()
    client.post(f"/api/mission-control/sessions/{started['id']}/complete", json={})
    after = client.get("/api/domains/life/records").json()
    assert before == after
