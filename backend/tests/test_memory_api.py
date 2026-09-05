from __future__ import annotations

from fastapi.testclient import TestClient


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def test_create_list_get_memory(client: TestClient) -> None:
    body_id = _domain_id(client, "body")
    resp = client.post(
        "/api/memories",
        json={
            "scope": "domain",
            "domain_id": body_id,
            "kind": "health_context",
            "title": "Knee issue",
            "content": "History of knee pain.",
        },
    )
    assert resp.status_code == 201
    memory_id = resp.json()["id"]

    listed = client.get("/api/memories", params={"domain_id": body_id}).json()
    assert any(m["id"] == memory_id for m in listed)

    detail = client.get(f"/api/memories/{memory_id}").json()
    assert detail["current_content"] == "History of knee pain."
    assert len(detail["versions"]) == 1


def test_edit_memory_creates_version_two(client: TestClient) -> None:
    resp = client.post(
        "/api/memories",
        json={"scope": "global", "domain_id": None, "kind": "preference", "title": "Name", "content": "v1"},
    )
    memory_id = resp.json()["id"]

    edit_resp = client.post(f"/api/memories/{memory_id}/edit", json={"content": "v2"})
    assert edit_resp.status_code == 200

    detail = client.get(f"/api/memories/{memory_id}").json()
    assert len(detail["versions"]) == 2
    assert detail["current_content"] == "v2"


def test_archive_and_unarchive(client: TestClient) -> None:
    resp = client.post(
        "/api/memories",
        json={"scope": "global", "domain_id": None, "kind": "fact", "title": "T", "content": "c"},
    )
    memory_id = resp.json()["id"]

    archived = client.post(f"/api/memories/{memory_id}/archive").json()
    assert archived["status"] == "archived"

    unarchived = client.post(f"/api/memories/{memory_id}/unarchive").json()
    assert unarchived["status"] == "active"


def test_permanent_delete_requires_confirmation(client: TestClient) -> None:
    resp = client.post(
        "/api/memories",
        json={"scope": "global", "domain_id": None, "kind": "fact", "title": "Delete target", "content": "c"},
    )
    memory_id = resp.json()["id"]

    wrong = client.post(f"/api/memories/{memory_id}/delete", json={"confirm_title": "nope"})
    assert wrong.status_code == 422

    correct = client.post(f"/api/memories/{memory_id}/delete", json={"confirm_title": "Delete target"})
    assert correct.status_code == 204

    assert client.get(f"/api/memories/{memory_id}").status_code == 404


def test_memory_search_endpoint(client: TestClient) -> None:
    body_id = _domain_id(client, "body")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": body_id, "kind": "health_context", "title": "Knee issue", "content": "knee pain history"},
    )
    resp = client.get("/api/memories/search", params={"q": "knee"})
    assert resp.status_code == 200
    assert any(m["title"] == "Knee issue" for m in resp.json())


def test_domain_summary_crud(client: TestClient) -> None:
    resp = client.put("/api/domains/body/summary", json={"content": "Recovering from knee issue."})
    assert resp.status_code == 200
    assert resp.json()["current_content"] == "Recovering from knee issue."

    history = client.get("/api/domains/body/summary/history").json()
    assert len(history) == 1

    client.put("/api/domains/body/summary", json={"content": "Updated summary."})
    history2 = client.get("/api/domains/body/summary/history").json()
    assert len(history2) == 2

    cleared = client.delete("/api/domains/body/summary").json()
    assert cleared["current_content"] is None
    # History remains even after clearing.
    assert len(client.get("/api/domains/body/summary/history").json()) == 2


def test_structured_record_crud(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/body/records",
        json={"record_type": "body_weight", "occurred_at": "2026-08-25T00:00:00Z", "payload": {"kilograms": 80}},
    )
    assert resp.status_code == 201
    record_id = resp.json()["id"]

    listed = client.get("/api/domains/body/records").json()
    assert any(r["id"] == record_id for r in listed)

    archived = client.post(f"/api/records/{record_id}/archive").json()
    assert archived["archived_at"] is not None

    still_listed_with_flag = client.get(
        "/api/domains/body/records", params={"include_archived": True}
    ).json()
    assert any(r["id"] == record_id for r in still_listed_with_flag)

    default_listing = client.get("/api/domains/body/records").json()
    assert not any(r["id"] == record_id for r in default_listing)


def test_structured_record_wrong_domain_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/build/records",
        json={"record_type": "body_weight", "occurred_at": "2026-08-25T00:00:00Z", "payload": {"kilograms": 80}},
    )
    assert resp.status_code == 422


def test_records_scoped_to_domain_never_leak_across_domains(client: TestClient) -> None:
    client.post(
        "/api/domains/body/records",
        json={"record_type": "body_weight", "occurred_at": "2026-08-25T00:00:00Z", "payload": {"kilograms": 80}},
    )
    build_records = client.get("/api/domains/build/records").json()
    assert build_records == []


def test_fts_rebuild_and_status_endpoints(client: TestClient) -> None:
    body_id = _domain_id(client, "body")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": body_id, "kind": "health_context", "title": "Knee issue", "content": "knee content"},
    )
    rebuild = client.post("/api/memory-index/rebuild")
    assert rebuild.status_code == 200
    assert rebuild.json()["indexed_count"] >= 1

    status = client.get("/api/memory-index/status")
    assert status.status_code == 200
    assert status.json()["indexed_count"] >= 1


def test_pagination_limits_enforced(client: TestClient) -> None:
    resp = client.get("/api/memories", params={"limit": 500})
    assert resp.status_code == 422  # bounded — the server rejects an excessive limit

    resp_ok = client.get("/api/memories", params={"limit": 50})
    assert resp_ok.status_code == 200
