"""Actions, skills, versions, and audit history survive a full backend restart."""

from __future__ import annotations


def test_action_and_skill_state_survives_restart(restart_client_factory) -> None:
    client1 = restart_client_factory()

    create_resp = client1.post(
        "/api/skills",
        json={
            "slug": "restart-skill",
            "name": "Restart skill",
            "description": "d",
            "domain_id": None,
            "workflow_steps": [{"capability_id": "memory.create", "description": "log"}],
        },
    )
    skill_id = create_resp.json()["id"]
    client1.post(f"/api/skills/{skill_id}/activate")

    invoke_resp = client1.post(
        f"/api/skills/{skill_id}/invoke",
        json={"step_arguments": [{"scope": "global", "kind": "fact", "title": "restart-fact", "content": "c"}]},
    )
    proposal_id = invoke_resp.json()["proposals"][0]["id"]
    approve_resp = client1.post(
        f"/api/actions/{proposal_id}/approve",
        json={"payload_digest": invoke_resp.json()["proposals"][0]["payload_digest"]},
    )
    token = approve_resp.json()["confirmation_token"]
    client1.post(f"/api/actions/{proposal_id}/execute", json={"confirmation_token": token})

    client2 = restart_client_factory()

    skill_after = client2.get(f"/api/skills/{skill_id}").json()
    assert skill_after["skill"]["status"] == "active"
    assert len(skill_after["versions"]) == 1

    proposal_after = client2.get(f"/api/actions/{proposal_id}").json()
    assert proposal_after["proposal"]["status"] == "succeeded"
    assert [e["event_type"] for e in proposal_after["audit_events"]] == [
        "proposed",
        "approved",
        "executing",
        "succeeded",
    ]
