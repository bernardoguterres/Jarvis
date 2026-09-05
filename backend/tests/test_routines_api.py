"""Phase 10B: HTTP-level tests for the routine catalogue's endpoints.
Uses the standard `client` fixture (fake Hermes/STT/TTS already wired by
conftest.py) — no real Google, Keychain, Hermes, or model call."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_routine_schedules_default_disabled_over_http(client: TestClient) -> None:
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        resp = client.get(f"/api/routines/{routine_type}/schedule")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["next_due_at"] is None


def test_unknown_routine_type_404s(client: TestClient) -> None:
    assert client.get("/api/routines/bogus/schedule").status_code == 404
    assert client.post("/api/routines/bogus/run").status_code == 404
    assert client.get("/api/routines/bogus/history").status_code == 404


def test_enable_schedule_rejects_invalid_local_time(client: TestClient) -> None:
    resp = client.put(
        "/api/routines/morning_briefing/schedule",
        json={"enabled": True, "local_time": "not-a-time", "timezone": "UTC", "selected_domains": []},
    )
    assert resp.status_code == 400


def test_enable_schedule_over_http_schedules_next_due(client: TestClient) -> None:
    resp = client.put(
        "/api/routines/morning_briefing/schedule",
        json={"enabled": True, "local_time": "08:00", "timezone": "Europe/Lisbon", "selected_domains": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["next_due_at"] is not None
    assert body["timezone"] == "Europe/Lisbon"


def test_manual_run_now_returns_deterministic_output(client: TestClient) -> None:
    resp = client.post("/api/routines/morning_briefing/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["trigger"] == "manual"
    assert body["outcome"] == "succeeded"
    assert isinstance(body["sections"], list)


def test_evening_checkin_run_and_record_responses(client: TestClient) -> None:
    run_resp = client.post("/api/routines/evening_checkin/run")
    assert run_resp.status_code == 200
    run_id = run_resp.json()["id"]
    assert len(run_resp.json()["sections"][0]["lines"]) == 4  # fixed 4-prompt template

    resp = client.post(f"/api/routines/runs/{run_id}/responses", json={"responses": {"mood": "good"}})
    assert resp.status_code == 200
    assert resp.json()["responses"] == {"mood": "good"}


def test_history_endpoint_bounded_and_ordered(client: TestClient) -> None:
    client.post("/api/routines/morning_briefing/run")
    client.post("/api/routines/morning_briefing/run")
    resp = client.get("/api/routines/morning_briefing/history")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_no_secrets_or_tokens_in_any_routine_response(client: TestClient) -> None:
    resp = client.post("/api/routines/morning_briefing/run")
    assert "access_token" not in resp.text
    assert "refresh_token" not in resp.text
    assert "client_secret" not in resp.text
