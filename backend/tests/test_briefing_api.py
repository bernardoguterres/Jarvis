"""Phase 12A: HTTP-level tests for the on-demand Home briefing's endpoints.
Uses the standard `client` fixture (fake Hermes/STT/TTS already wired by
conftest.py) — no real Google, Keychain, Hermes, or model call."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_default_settings_match_recorded_privacy_selection(client: TestClient) -> None:
    resp = client.get("/api/briefing/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"include_body": True, "include_mind": False, "include_people": False}


def test_update_settings_toggles_body_only(client: TestClient) -> None:
    resp = client.put("/api/briefing/settings", json={"include_body": False})
    assert resp.status_code == 200
    assert resp.json() == {"include_body": False, "include_mind": False, "include_people": False}

    # Confirm it actually persisted, not just echoed back.
    resp2 = client.get("/api/briefing/settings")
    assert resp2.json()["include_body"] is False


def test_home_briefing_empty_state(client: TestClient) -> None:
    resp = client.get("/api/briefing/home")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["include_body"] is True
    assert body["include_mind"] is False
    assert body["include_people"] is False
    assert "generated_at" in body


def test_home_briefing_reflects_a_life_task_overdue(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/life/records",
        json={
            "record_type": "life_task",
            "occurred_at": "2026-08-20T09:00:00Z",
            "payload": {"title": "Renew passport", "due_date": "2020-01-01"},
        },
    )
    assert resp.status_code == 201, resp.text

    briefing = client.get("/api/briefing/home").json()
    titles = [i["title"] for i in briefing["items"]]
    assert "Renew passport" in titles
    now_item = next(i for i in briefing["items"] if i["title"] == "Renew passport")
    assert now_item["category"] == "now"
    assert now_item["link_target"] == "domain:life"
    assert now_item["source_ids"]


def test_home_briefing_never_calls_the_fake_provider(client: TestClient) -> None:
    """The `client` fixture's FakeProvider (conftest.py) would raise if the
    real send-turn code path were ever exercised for something as trivial
    as assembling a fetch — confirms the endpoint succeeds without ever
    touching /api/agent/status's underlying provider call count changing."""
    before = client.get("/api/agent/status").json()
    resp = client.get("/api/briefing/home")
    assert resp.status_code == 200
    after = client.get("/api/agent/status").json()
    assert before == after


def _create_overdue_life_task(client: TestClient, title: str = "Renew passport") -> None:
    resp = client.post(
        "/api/domains/life/records",
        json={
            "record_type": "life_task",
            "occurred_at": "2026-08-20T09:00:00Z",
            "payload": {"title": title, "due_date": "2020-01-01"},
        },
    )
    assert resp.status_code == 201, resp.text


def test_new_item_carries_change_state_and_fingerprint(client: TestClient) -> None:
    _create_overdue_life_task(client)
    body = client.get("/api/briefing/home").json()
    item = body["items"][0]
    assert item["change_state"] == "new"
    assert item["fingerprint"]
    assert body["acknowledged_and_snoozed"] == []


def test_refresh_trigger_query_param_does_not_change_the_home_baseline(client: TestClient) -> None:
    _create_overdue_life_task(client)
    client.get("/api/briefing/home")  # trigger=home_view (default)
    body = client.get("/api/briefing/home?trigger=home_refresh").json()
    assert body["items"][0]["change_state"] == "ongoing"  # never "new" again just because trigger differs

    history = client.get("/api/briefing/history?consumer=home").json()
    triggers = {row["trigger"] for row in history}
    assert triggers == {"home_view", "home_refresh"} or triggers == {"home_view"}  # dedup may collapse


def test_acknowledge_snooze_restore_over_http(client: TestClient) -> None:
    _create_overdue_life_task(client)
    body = client.get("/api/briefing/home").json()
    stable_key = body["items"][0]["id"]

    ack_resp = client.post(f"/api/briefing/items/{stable_key}/acknowledge")
    assert ack_resp.status_code == 200
    assert ack_resp.json()["suppressed"] == "acknowledged"

    after_ack = client.get("/api/briefing/home").json()
    assert after_ack["items"] == []
    assert after_ack["acknowledged_and_snoozed"][0]["kind"] == "acknowledged"

    restore_resp = client.post(f"/api/briefing/items/{stable_key}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["suppressed"] is None

    after_restore = client.get("/api/briefing/home").json()
    assert len(after_restore["items"]) == 1

    snooze_resp = client.post(f"/api/briefing/items/{stable_key}/snooze", json={"duration": "1h"})
    assert snooze_resp.status_code == 200
    assert snooze_resp.json()["suppressed"] == "snoozed"

    after_snooze = client.get("/api/briefing/home").json()
    assert after_snooze["items"] == []
    assert after_snooze["acknowledged_and_snoozed"][0]["kind"] == "snoozed"
    assert after_snooze["acknowledged_and_snoozed"][0]["duration_key"] == "1h"


def test_acknowledge_unknown_item_404s(client: TestClient) -> None:
    resp = client.post("/api/briefing/items/life_task:does-not-exist/acknowledge")
    assert resp.status_code == 404


def test_snooze_invalid_duration_rejected_over_http(client: TestClient) -> None:
    _create_overdue_life_task(client)
    body = client.get("/api/briefing/home").json()
    stable_key = body["items"][0]["id"]
    resp = client.post(f"/api/briefing/items/{stable_key}/snooze", json={"duration": "3_days"})
    assert resp.status_code == 422  # rejected by the fixed pydantic Literal before it ever reaches the service


def test_restore_never_executes_the_phase8_action_lifecycle(client: TestClient) -> None:
    """Acknowledge/snooze/restore must never enter the Phase 8
    propose->approve->execute lifecycle — confirmed by checking the
    Actions Centre's own listing stays empty throughout."""
    _create_overdue_life_task(client)
    body = client.get("/api/briefing/home").json()
    stable_key = body["items"][0]["id"]
    client.post(f"/api/briefing/items/{stable_key}/acknowledge")
    client.post(f"/api/briefing/items/{stable_key}/restore")
    actions = client.get("/api/actions").json()
    assert actions == []


def test_briefing_history_bounded_and_ordered(client: TestClient) -> None:
    _create_overdue_life_task(client)
    client.get("/api/briefing/home")
    history = client.get("/api/briefing/history?consumer=home&limit=5").json()
    assert 1 <= len(history) <= 5
    assert history[0]["consumer"] == "home"


def test_no_secrets_in_home_briefing_response(client: TestClient) -> None:
    _create_overdue_life_task(client)
    body = client.get("/api/briefing/home").json()
    dumped = str(body)
    for forbidden in ("access_token", "refresh_token", "bearer", "confirmation_token", "client_secret"):
        assert forbidden not in dumped.lower()


def test_rapid_consecutive_refreshes_do_not_spam_history(client: TestClient) -> None:
    """A proxy for 'concurrent refreshes cannot create contradictory
    baselines': several rapid GETs (simulating a double click / a React
    effect double-invoke) must dedupe into a single snapshot row and
    never disagree about the item's change_state."""
    _create_overdue_life_task(client)
    results = [client.get("/api/briefing/home").json() for _ in range(5)]
    change_states = {r["items"][0]["change_state"] for r in results[1:]}
    assert change_states == {"ongoing"}  # only the very first is "new"; every repeat agrees
    history = client.get("/api/briefing/history?consumer=home").json()
    assert len(history) == 1


def test_briefing_continuity_survives_backend_restart(restart_client_factory) -> None:
    client1 = restart_client_factory()
    _create_overdue_life_task(client1)
    first = client1.get("/api/briefing/home").json()
    stable_key = first["items"][0]["id"]
    client1.post(f"/api/briefing/items/{stable_key}/acknowledge")
    assert client1.get("/api/briefing/home").json()["items"] == []

    client2 = restart_client_factory()
    after_restart = client2.get("/api/briefing/home").json()
    assert after_restart["items"] == []  # the acknowledgement survived
    assert after_restart["acknowledged_and_snoozed"][0]["stable_key"] == stable_key

    client2.post(f"/api/briefing/items/{stable_key}/restore")
    assert len(client2.get("/api/briefing/home").json()["items"]) == 1
