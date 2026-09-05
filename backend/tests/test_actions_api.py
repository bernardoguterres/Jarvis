from __future__ import annotations

from fastapi.testclient import TestClient


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def test_capabilities_endpoint_lists_the_fixed_registry(client: TestClient) -> None:
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    ids = {c["capability_id"] for c in resp.json()}
    assert ids == {
        "memory.create",
        "structured_record.create",
        "domain_summary.update",
        "google_calendar.event.create",
        "google_calendar.event.update",
        "google_calendar.event.delete",
    }
    assert all(c["permission_level"] == "confirm" for c in resp.json())


def test_propose_reject_unknown_capability(client: TestClient) -> None:
    resp = client.post(
        "/api/actions",
        json={"capability_id": "shell.exec", "domain_id": None, "arguments": {}, "reason": "nope"},
    )
    assert resp.status_code == 400


def test_full_http_lifecycle(client: TestClient) -> None:
    resp = client.post(
        "/api/actions",
        json={
            "capability_id": "memory.create",
            "domain_id": None,
            "arguments": {"scope": "global", "kind": "fact", "title": "HTTP test", "content": "c"},
            "reason": "http lifecycle test",
        },
    )
    assert resp.status_code == 201
    proposal = resp.json()
    assert proposal["status"] == "proposed"

    approve_resp = client.post(
        f"/api/actions/{proposal['id']}/approve", json={"payload_digest": proposal["payload_digest"]}
    )
    assert approve_resp.status_code == 200
    approved = approve_resp.json()
    assert approved["status"] == "approved"
    assert approved["confirmation_token"]

    exec_resp = client.post(
        f"/api/actions/{proposal['id']}/execute",
        json={"confirmation_token": approved["confirmation_token"]},
    )
    assert exec_resp.status_code == 200
    executed = exec_resp.json()
    assert executed["status"] == "succeeded"
    assert executed["result"]["memory_item_id"]

    # Replay over HTTP must fail even with the correct (now-used) token.
    replay_resp = client.post(
        f"/api/actions/{proposal['id']}/execute",
        json={"confirmation_token": approved["confirmation_token"]},
    )
    assert replay_resp.status_code == 403

    detail_resp = client.get(f"/api/actions/{proposal['id']}")
    assert detail_resp.status_code == 200
    history = detail_resp.json()["audit_events"]
    assert [e["event_type"] for e in history] == ["proposed", "approved", "executing", "succeeded"]


def test_a_proposal_stuck_executing_by_a_crash_is_recovered_on_the_next_real_startup(
    restart_client_factory,
) -> None:
    """End-to-end version of the action_service unit test: uses a real
    second app startup (restart_client_factory), not a direct function
    call, to prove app.main's lifespan actually wires in the recovery."""
    client1 = restart_client_factory()
    resp = client1.post(
        "/api/actions",
        json={
            "capability_id": "memory.create",
            "domain_id": None,
            "arguments": {"scope": "global", "kind": "fact", "title": "Stuck", "content": "c"},
            "reason": "test",
        },
    )
    proposal_id = resp.json()["id"]
    payload_digest = resp.json()["payload_digest"]
    approved = client1.post(
        f"/api/actions/{proposal_id}/approve", json={"payload_digest": payload_digest}
    ).json()

    # Simulate the exact moment a crash/kill would leave behind: marked
    # "executing" by a process that never got to record the outcome.
    from app.models_actions import ActionProposal

    session_factory = client1.app.state.session_factory
    with session_factory() as session:
        stuck = session.get(ActionProposal, proposal_id)
        stuck.status = "executing"
        session.commit()

    client2 = restart_client_factory()
    detail = client2.get(f"/api/actions/{proposal_id}").json()
    assert detail["proposal"]["status"] == "failed"
    assert "unknown" in detail["proposal"]["error_summary"].lower()
    assert [e["event_type"] for e in detail["audit_events"]] == ["proposed", "approved", "failed"]

    # Genuinely terminal — the now-unused confirmation token cannot revive it.
    exec_resp = client2.post(
        f"/api/actions/{proposal_id}/execute", json={"confirmation_token": approved["confirmation_token"]}
    )
    assert exec_resp.status_code == 403


def test_approve_rejects_wrong_digest_over_http(client: TestClient) -> None:
    resp = client.post(
        "/api/actions",
        json={
            "capability_id": "memory.create",
            "domain_id": None,
            "arguments": {"scope": "global", "kind": "fact", "title": "T", "content": "c"},
            "reason": "test",
        },
    )
    proposal = resp.json()
    bad = client.post(f"/api/actions/{proposal['id']}/approve", json={"payload_digest": "wrong"})
    assert bad.status_code == 409


def test_deny_over_http(client: TestClient) -> None:
    resp = client.post(
        "/api/actions",
        json={
            "capability_id": "memory.create",
            "domain_id": None,
            "arguments": {"scope": "global", "kind": "fact", "title": "T", "content": "c"},
            "reason": "test",
        },
    )
    proposal = resp.json()
    deny_resp = client.post(f"/api/actions/{proposal['id']}/deny", json={"reason": "not now"})
    assert deny_resp.status_code == 200
    assert deny_resp.json()["status"] == "denied"

    exec_resp = client.post(f"/api/actions/{proposal['id']}/execute", json={"confirmation_token": "x"})
    assert exec_resp.status_code == 403


def test_list_and_filter_by_status(client: TestClient) -> None:
    client.post(
        "/api/actions",
        json={
            "capability_id": "memory.create",
            "domain_id": None,
            "arguments": {"scope": "global", "kind": "fact", "title": "A", "content": "c"},
            "reason": "test",
        },
    )
    resp = client.get("/api/actions", params={"status": "proposed"})
    assert resp.status_code == 200
    assert all(p["status"] == "proposed" for p in resp.json())


def test_structured_record_proposal_requires_matching_domain(client: TestClient) -> None:
    mind_id = _domain_id(client, "mind")
    resp = client.post(
        "/api/actions",
        json={
            "capability_id": "structured_record.create",
            "domain_id": mind_id,
            "arguments": {"record_type": "body_weight", "payload": {"kilograms": 70}},
            "reason": "wrong domain",
        },
    )
    assert resp.status_code == 400
