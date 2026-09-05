from __future__ import annotations

from fastapi.testclient import TestClient


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def test_example_templates_are_seeded_as_drafts(client: TestClient) -> None:
    resp = client.get("/api/skills", params={"status": "draft"})
    assert resp.status_code == 200
    slugs = {s["slug"] for s in resp.json()}
    assert {
        "example-body-weekly-checkin",
        "example-build-project-checkpoint",
        "example-path-deadline-review",
        "example-life-daily-planning",
    }.issubset(slugs)
    # None of them are silently active.
    active_resp = client.get("/api/skills", params={"status": "active"})
    active_slugs = {s["slug"] for s in active_resp.json()}
    assert active_slugs.isdisjoint({"example-body-weekly-checkin"})


def test_create_review_activate_invoke_flow(client: TestClient) -> None:
    body_id = _domain_id(client, "body")

    create_resp = client.post(
        "/api/skills",
        json={
            "slug": "http-test-skill",
            "name": "HTTP test skill",
            "description": "A test skill created over HTTP.",
            "domain_id": body_id,
            "invocation_phrases": ["run the http test"],
            "workflow_steps": [
                {"capability_id": "structured_record.create", "description": "Log a weight entry"}
            ],
        },
    )
    assert create_resp.status_code == 201
    skill = create_resp.json()
    assert skill["status"] == "draft"

    detail_resp = client.get(f"/api/skills/{skill['id']}")
    assert detail_resp.status_code == 200
    assert len(detail_resp.json()["versions"]) == 1

    invoke_before_active = client.post(
        f"/api/skills/{skill['id']}/invoke",
        json={"step_arguments": [{"record_type": "body_weight", "payload": {"kilograms": 71}}]},
    )
    assert invoke_before_active.status_code == 400  # not active yet

    activate_resp = client.post(f"/api/skills/{skill['id']}/activate")
    assert activate_resp.status_code == 200
    assert activate_resp.json()["status"] == "active"

    invoke_resp = client.post(
        f"/api/skills/{skill['id']}/invoke",
        json={"step_arguments": [{"record_type": "body_weight", "payload": {"kilograms": 71}}]},
    )
    assert invoke_resp.status_code == 200
    proposals = invoke_resp.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["domain_id"] == body_id
    assert proposals[0]["status"] == "proposed"
    assert proposals[0]["source"].startswith(f"skill:{skill['id']}:v")


def test_edit_demotes_active_skill_to_draft(client: TestClient) -> None:
    create_resp = client.post(
        "/api/skills",
        json={
            "slug": "edit-http",
            "name": "Edit http",
            "description": "d",
            "domain_id": None,
            "workflow_steps": [{"capability_id": "memory.create", "description": "log"}],
        },
    )
    skill_id = create_resp.json()["id"]
    client.post(f"/api/skills/{skill_id}/activate")

    edit_resp = client.post(
        f"/api/skills/{skill_id}/edit",
        json={"workflow_steps": [{"capability_id": "memory.create", "description": "log (revised)"}]},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["status"] == "draft"


def test_archive_skill(client: TestClient) -> None:
    create_resp = client.post(
        "/api/skills",
        json={
            "slug": "archive-http",
            "name": "Archive http",
            "description": "d",
            "domain_id": None,
            "workflow_steps": [{"capability_id": "memory.create", "description": "log"}],
        },
    )
    skill_id = create_resp.json()["id"]
    archive_resp = client.post(f"/api/skills/{skill_id}/archive")
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == "archived"


def test_create_rejects_disallowed_capability_over_http(client: TestClient) -> None:
    resp = client.post(
        "/api/skills",
        json={
            "slug": "bad-capability",
            "name": "Bad",
            "description": "d",
            "domain_id": None,
            "workflow_steps": [{"capability_id": "terminal.exec", "description": "nope"}],
        },
    )
    assert resp.status_code == 400
