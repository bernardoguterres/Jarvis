"""Phase 12C: HTTP-level tests for Mission Focus's endpoints. Uses the
standard `client` fixture (fake Hermes/STT/TTS already wired by
conftest.py) — no real Google/Keychain/Hermes/model call."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _life_id(client: TestClient) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == "life")


def _create_life_task(client: TestClient, title: str = "Renew passport") -> str:
    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": title, "due_date": "2020-01-01"}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_empty_mission_focus(client: TestClient) -> None:
    resp = client.get("/api/mission-focus")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_pins"] == []
    assert body["max_active_pins"] == 5
    assert body["default_visible"] == 3


def test_create_pin_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    resp = client.post(
        "/api/mission-focus/pins",
        json={"source_type": "life_task", "source_id": task_id, "next_action": "Book an appointment"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rank"] == 1
    assert body["domain_slug"] == "life"
    assert body["title"] == "Renew passport"
    assert body["status"] == "active"


def test_create_pin_rejects_unknown_source_type(client: TestClient) -> None:
    resp = client.post(
        "/api/mission-focus/pins", json={"source_type": "mind_checkin", "source_id": "x", "next_action": "y"}
    )
    assert resp.status_code == 422  # rejected by the fixed pydantic Literal before it reaches the service


def test_create_pin_rejects_nonexistent_source(client: TestClient) -> None:
    resp = client.post(
        "/api/mission-focus/pins", json={"source_type": "life_task", "source_id": "does-not-exist", "next_action": "y"}
    )
    assert resp.status_code == 400


def test_create_pin_requires_next_action(client: TestClient) -> None:
    task_id = _create_life_task(client)
    resp = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": ""})
    assert resp.status_code == 422


def test_five_pin_limit_reached_reported_clearly(client: TestClient) -> None:
    ids = [_create_life_task(client, title=f"Task {i}") for i in range(6)]
    for tid in ids[:5]:
        resp = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": tid, "next_action": "a"})
        assert resp.status_code == 201
    resp = client.get("/api/mission-focus")
    assert len(resp.json()["active_pins"]) == 5

    sixth = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": ids[5], "next_action": "a"})
    assert sixth.status_code == 400
    assert "5" in sixth.json()["detail"]


def test_duplicate_pin_rejected_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "a"})
    resp = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "b"})
    assert resp.status_code == 400


def test_update_pin_metadata_over_http(client: TestClient) -> None:
    task_id = _create_life_task(client)
    pin = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "a"}).json()
    resp = client.put(f"/api/mission-focus/pins/{pin['id']}", json={"next_action": "Call the office", "blocker": "Waiting on docs"})
    assert resp.status_code == 200
    assert resp.json()["next_action"] == "Call the office"
    assert resp.json()["blocker"] == "Waiting on docs"


def test_unpin_over_http_never_touches_the_source(client: TestClient) -> None:
    task_id = _create_life_task(client)
    pin = client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "a"}).json()
    resp = client.post(f"/api/mission-focus/pins/{pin['id']}/unpin")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unpinned"

    assert client.get("/api/mission-focus").json()["active_pins"] == []
    records = client.get("/api/domains/life/records").json()
    task = next(r for r in records if r["id"] == task_id)
    assert task["archived_at"] is None


def test_reorder_over_http(client: TestClient) -> None:
    ids = [_create_life_task(client, title=f"Task {i}") for i in range(3)]
    pins = [
        client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": tid, "next_action": "a"}).json()
        for tid in ids
    ]
    new_order = [pins[2]["id"], pins[0]["id"], pins[1]["id"]]
    resp = client.put("/api/mission-focus/reorder", json={"pin_ids": new_order})
    assert resp.status_code == 200
    assert [p["id"] for p in resp.json()["active_pins"]] == new_order
    assert [p["rank"] for p in resp.json()["active_pins"]] == [1, 2, 3]


def test_reorder_rejects_incomplete_list(client: TestClient) -> None:
    ids = [_create_life_task(client, title=f"Task {i}") for i in range(2)]
    pins = [
        client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": tid, "next_action": "a"}).json()
        for tid in ids
    ]
    resp = client.put("/api/mission-focus/reorder", json={"pin_ids": [pins[0]["id"]]})
    assert resp.status_code == 400


def test_mission_focus_appears_in_home_briefing(client: TestClient) -> None:
    task_id = _create_life_task(client)
    client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "Book slot"})
    briefing = client.get("/api/briefing/home").json()
    assert len(briefing["mission_focus"]) == 1
    assert briefing["mission_focus"][0]["next_action"] == "Book slot"
    pinned_items = [i for i in briefing["items"] if i.get("pinned")]
    assert len(pinned_items) == 1


def test_no_secrets_in_mission_focus_responses(client: TestClient) -> None:
    task_id = _create_life_task(client)
    client.post("/api/mission-focus/pins", json={"source_type": "life_task", "source_id": task_id, "next_action": "Book slot"})
    dumped = str(client.get("/api/mission-focus").json())
    for forbidden in ("access_token", "refresh_token", "bearer", "confirmation_token", "client_secret"):
        assert forbidden not in dumped.lower()


def test_mission_focus_never_calls_a_model(client: TestClient) -> None:
    before = client.get("/api/agent/status").json()
    _create_life_task(client)
    client.get("/api/mission-focus")
    after = client.get("/api/agent/status").json()
    assert before == after
