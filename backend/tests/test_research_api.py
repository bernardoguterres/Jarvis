"""Phase 12E: HTTP-level tests for the Research Workspace endpoints. Uses
the standard `client` fixture (fake Hermes/STT/TTS already wired by
conftest.py) — evidence search/CRUD/notes/deterministic-brief routes
never call a model; only `POST .../briefs/draft` does, and that is
covered by `client_with_fake_provider` here."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_life_task(client: TestClient, title: str) -> str:
    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": title}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_mind_record(client: TestClient, mood: str) -> str:
    resp = client.post(
        "/api/domains/mind/records",
        json={"record_type": "mind_checkin", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"mood": mood}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_workspace(client: TestClient, **overrides) -> dict:
    payload = {"title": "Tokenizer choice for Alpha"}
    payload.update(overrides)
    resp = client.post("/api/research/workspaces", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- workspace CRUD ------------------------------------------------------------


def test_create_and_get_workspace(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(f"/api/research/workspaces/{ws['id']}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Tokenizer choice for Alpha"
    assert resp.json()["included_domain_slugs"] == ["life", "path", "build"]


def test_get_unknown_workspace_returns_404(client: TestClient) -> None:
    resp = client.get("/api/research/workspaces/does-not-exist")
    assert resp.status_code == 404


def test_create_workspace_malformed_title_returns_422(client: TestClient) -> None:
    resp = client.post("/api/research/workspaces", json={"title": ""})
    assert resp.status_code == 422


def test_list_workspaces_status_filter(client: TestClient) -> None:
    active_ws = _create_workspace(client, title="active one")
    archived_ws = _create_workspace(client, title="archived one")
    client.post(f"/api/research/workspaces/{archived_ws['id']}/archive")

    active = client.get("/api/research/workspaces", params={"status": "active"}).json()
    archived = client.get("/api/research/workspaces", params={"status": "archived"}).json()
    assert {w["id"] for w in active} == {active_ws["id"]}
    assert {w["id"] for w in archived} == {archived_ws["id"]}


def test_bad_status_filter_returns_400(client: TestClient) -> None:
    resp = client.get("/api/research/workspaces", params={"status": "not-a-status"})
    assert resp.status_code == 400


def test_archive_then_reopen_workspace(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(f"/api/research/workspaces/{ws['id']}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
    resp = client.post(f"/api/research/workspaces/{ws['id']}/reopen")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


def test_update_workspace_domain_policy(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.put(f"/api/research/workspaces/{ws['id']}", json={"included_domain_slugs": ["mind"]})
    assert resp.status_code == 200
    assert resp.json()["included_domain_slugs"] == ["mind"]
    # Omitting the field entirely on a later PUT leaves it untouched.
    resp = client.put(f"/api/research/workspaces/{ws['id']}", json={"title": "renamed"})
    assert resp.json()["included_domain_slugs"] == ["mind"]
    assert resp.json()["title"] == "renamed"


# --- evidence discovery (delegates to Recall) -----------------------------------


def test_evidence_search_scoped_to_workspace_policy(client: TestClient) -> None:
    ws = _create_workspace(client, included_domain_slugs=["life"])
    _create_life_task(client, "unique-search-marker task")
    _create_mind_record(client, "unique-search-marker mood")  # excluded by policy

    resp = client.get(f"/api/research/workspaces/{ws['id']}/evidence/search", params={"q": "unique-search-marker"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["domain_slug"] == "life"


def test_evidence_search_unknown_workspace_returns_404(client: TestClient) -> None:
    resp = client.get("/api/research/workspaces/nope/evidence/search", params={"q": "x"})
    assert resp.status_code == 404


# --- evidence CRUD ---------------------------------------------------------------


def test_add_evidence_idempotent_over_http(client: TestClient) -> None:
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "task for evidence")
    first = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence",
        json={"source_type": "structured_record", "source_id": task_id, "classification": "supporting"},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence",
        json={"source_type": "structured_record", "source_id": task_id},
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]

    listing = client.get(f"/api/research/workspaces/{ws['id']}/evidence")
    assert len(listing.json()) == 1


def test_add_evidence_sensitive_domain_default_rejected_over_http(client: TestClient) -> None:
    ws = _create_workspace(client)  # default policy: life/path/build
    mind_id = _create_mind_record(client, "anxious")
    resp = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": mind_id}
    )
    assert resp.status_code == 400


def test_add_evidence_malformed_source_type_returns_422(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence",
        json={"source_type": "not_a_real_type", "source_id": "x"},
    )
    assert resp.status_code == 422


def test_add_evidence_malformed_source_id_returns_clean_error(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence",
        json={"source_type": "structured_record", "source_id": "definitely-does-not-exist"},
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_update_evidence_classification(client: TestClient) -> None:
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "task")
    evidence = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id}
    ).json()
    resp = client.put(
        f"/api/research/workspaces/{ws['id']}/evidence/{evidence['id']}", json={"classification": "contradicting"}
    )
    assert resp.status_code == 200
    assert resp.json()["classification"] == "contradicting"


def test_remove_evidence_over_http(client: TestClient) -> None:
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "task")
    evidence = client.post(
        f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id}
    ).json()
    resp = client.post(f"/api/research/workspaces/{ws['id']}/evidence/{evidence['id']}/remove")
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"
    assert client.get(f"/api/research/workspaces/{ws['id']}/evidence").json() == []


# --- notes ----------------------------------------------------------------------


def test_notes_crud_over_http(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(f"/api/research/workspaces/{ws['id']}/notes", json={"content": "A provisional claim."})
    assert resp.status_code == 201
    note_id = resp.json()["id"]

    resp = client.put(f"/api/research/workspaces/{ws['id']}/notes/{note_id}", json={"content": "Updated claim."})
    assert resp.status_code == 200
    assert resp.json()["content"] == "Updated claim."

    resp = client.post(f"/api/research/workspaces/{ws['id']}/notes/{note_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
    assert client.get(f"/api/research/workspaces/{ws['id']}/notes").json() == []


def test_note_with_unknown_linked_evidence_returns_clean_error(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(
        f"/api/research/workspaces/{ws['id']}/notes",
        json={"content": "x", "linked_evidence_ids": ["does-not-exist"]},
    )
    assert resp.status_code == 400


# --- briefs -----------------------------------------------------------------------


def test_deterministic_brief_generation_and_versioning_over_http(client: TestClient) -> None:
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "evidence task")
    client.post(f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id})

    v1 = client.post(f"/api/research/workspaces/{ws['id']}/briefs/deterministic")
    assert v1.status_code == 201
    assert v1.json()["version_number"] == 1

    v2 = client.post(f"/api/research/workspaces/{ws['id']}/briefs/deterministic")
    assert v2.json()["version_number"] == 2

    listing = client.get(f"/api/research/workspaces/{ws['id']}/briefs").json()
    assert len(listing) == 2

    detail = client.get(f"/api/research/workspaces/{ws['id']}/briefs/{v1.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["citations"][0]["available"] is True


def test_deterministic_brief_with_no_evidence_returns_400(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.post(f"/api/research/workspaces/{ws['id']}/briefs/deterministic")
    assert resp.status_code == 400


def test_workspace_reports_latest_brief_version(client: TestClient) -> None:
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "evidence task")
    client.post(f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id})
    client.post(f"/api/research/workspaces/{ws['id']}/briefs/deterministic")
    detail = client.get(f"/api/research/workspaces/{ws['id']}").json()
    assert detail["latest_brief_version"] == 1
    assert detail["evidence_count"] == 1


def test_draft_with_jarvis_over_http_uses_fake_provider(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    ws = _create_workspace(client)
    task_id = _create_life_task(client, "evidence task")
    client.post(f"/api/research/workspaces/{ws['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id})

    resp = client.post(f"/api/research/workspaces/{ws['id']}/briefs/draft")
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "model"
    assert body["model_meta"]["provider"] == "fake"
    assert "Jarvis model-generated draft" in body["title"]


def test_draft_with_no_evidence_returns_clean_502_and_no_model_call(client_with_fake_provider: TestClient, fake_provider) -> None:
    client = client_with_fake_provider
    ws = _create_workspace(client)
    resp = client.post(f"/api/research/workspaces/{ws['id']}/briefs/draft")
    assert resp.status_code == 502
    assert fake_provider.sent_messages == []


def test_get_unknown_brief_version_returns_404(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(f"/api/research/workspaces/{ws['id']}/briefs/does-not-exist")
    assert resp.status_code == 404
