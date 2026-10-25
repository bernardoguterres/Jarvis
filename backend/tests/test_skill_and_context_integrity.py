"""Regression tests for skill invocation atomicity and sensitivity scoping.

Before the fix, a two-step skill whose second step was invalid returned a
500 and left the first step's proposal behind, and a global memory marked
sensitive was sent to the model in every conversation, including BUILD.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _two_step_skill(client: TestClient) -> str:
    created = client.post(
        "/api/skills",
        json={
            "slug": "two-step",
            "name": "Two step",
            "description": "d",
            "workflow_steps": [
                {"capability_id": "memory.create", "description": "a"},
                {"capability_id": "memory.create", "description": "b"},
            ],
        },
    )
    assert created.status_code in (200, 201), created.text
    skill_id = created.json()["id"]
    assert client.post(f"/api/skills/{skill_id}/activate").status_code == 200
    return skill_id


def test_invalid_later_step_creates_no_proposals_and_returns_400(client: TestClient) -> None:
    skill_id = _two_step_skill(client)
    before = len(client.get("/api/actions").json())
    r = client.post(
        f"/api/skills/{skill_id}/invoke",
        json={
            "step_arguments": [
                {"scope": "global", "kind": "fact", "title": "step1", "content": "ok"},
                {"scope": "global", "kind": "fact", "title": "", "content": "empty title"},
            ]
        },
    )
    assert r.status_code == 400
    assert "Step 2" in r.json()["detail"]
    assert len(client.get("/api/actions").json()) == before


def test_non_object_step_arguments_are_rejected_cleanly(client: TestClient) -> None:
    skill_id = _two_step_skill(client)
    r = client.post(f"/api/skills/{skill_id}/invoke", json={"step_arguments": [{"scope": "global"}, "nope"]})
    assert r.status_code in (400, 422)


def test_valid_invocation_still_creates_every_proposal(client: TestClient) -> None:
    skill_id = _two_step_skill(client)
    r = client.post(
        f"/api/skills/{skill_id}/invoke",
        json={
            "step_arguments": [
                {"scope": "global", "kind": "fact", "title": "a", "content": "ok"},
                {"scope": "global", "kind": "fact", "title": "b", "content": "ok"},
            ]
        },
    )
    assert r.status_code == 200
    assert len(r.json()["proposals"]) == 2


def test_sensitive_global_memory_never_reaches_the_model(client_with_fake_provider: TestClient, fake_provider) -> None:
    client = client_with_fake_provider
    for title, sensitivity in (("Plain fact", "normal"), ("Private diagnosis", "sensitive")):
        r = client.post(
            "/api/memories",
            json={"scope": "global", "kind": "fact", "title": title, "content": f"{title} body", "sensitivity": sensitivity},
        )
        assert r.status_code == 201
    conversation_id = client.post("/api/domains/build/conversations", json={"title": "t"}).json()["id"]
    r = client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"content": "hi", "idempotency_key": "k", "additional_domain_ids": []},
    )
    assert r.json()["status"] == "succeeded"
    sent = fake_provider.sent_system_prompts[-1]
    assert "Plain fact" in sent
    assert "Private diagnosis" not in sent


def test_concurrent_briefing_and_mission_candidates_do_not_500(client: TestClient) -> None:
    """Home fetches both in parallel; a brand-new concern made both insert
    the same ledger row and one request failed with a 500 (seen in live use)."""
    import threading

    for i in range(5):
        r = client.post(
            "/api/domains/build/records",
            json={
                "record_type": "build_checkpoint",
                "occurred_at": "2026-10-18T10:00:00Z",
                "payload": {"project": f"P{i}", "summary": f"checkpoint {i}"},
            },
        )
        assert r.status_code == 201
        barrier = threading.Barrier(2)
        codes: list[int] = []

        def go(path: str) -> None:
            barrier.wait()
            codes.append(client.get(path).status_code)

        threads = [
            threading.Thread(target=go, args=("/api/briefing/home",)),
            threading.Thread(target=go, args=("/api/mission-control/candidates",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert codes == [200, 200], (i, codes)
