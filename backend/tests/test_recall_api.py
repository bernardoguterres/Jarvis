"""Phase 12D: HTTP-level tests for Recall's endpoints. Uses the standard
`client` fixture (fake Hermes/STT/TTS already wired by conftest.py) — no
real Google/Keychain/Hermes/model call, and no model call is ever
expected from `/api/recall/*` (search and rebuild are both pure local
reads/writes)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create_life_task(client: TestClient, title: str) -> str:
    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": title}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_search_with_no_query_returns_empty(client: TestClient) -> None:
    resp = client.get("/api/recall/search")
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total_considered"] == 0


def test_search_finds_a_real_life_task_by_default(client: TestClient) -> None:
    _create_life_task(client, "Renew passport before travel")
    resp = client.get("/api/recall/search", params={"q": "passport"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["domain_slug"] == "life"
    assert body["results"][0]["source_type"] == "structured_record"
    assert "<mark>" in body["results"][0]["snippet_html"]


def test_search_excludes_mind_by_default_over_http(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/mind/records",
        json={"record_type": "mind_checkin", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"mood": "anxious about deadline"}},
    )
    assert resp.status_code == 201
    resp = client.get("/api/recall/search", params={"q": "anxious"})
    assert resp.json()["results"] == []


def test_search_includes_mind_when_explicitly_requested_over_http(client: TestClient) -> None:
    client.post(
        "/api/domains/mind/records",
        json={"record_type": "mind_checkin", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"mood": "explicitmindtoken"}},
    )
    resp = client.get("/api/recall/search", params={"q": "explicitmindtoken", "domains": "mind"})
    body = resp.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["domain_slug"] == "mind"


def test_source_types_param_filters_results(client: TestClient) -> None:
    _create_life_task(client, "filtermarker task")
    resp = client.get("/api/recall/search", params={"q": "filtermarker", "source_types": "conversation"})
    assert resp.json()["results"] == []


def test_pagination_params_bounded(client: TestClient) -> None:
    resp = client.get("/api/recall/search", params={"q": "x", "limit": 10_000})
    assert resp.status_code == 422  # over the Query(le=...) bound


def test_rebuild_endpoint_reports_indexed_count(client: TestClient) -> None:
    _create_life_task(client, "rebuild target task")
    resp = client.post("/api/recall/rebuild")
    assert resp.status_code == 200
    assert resp.json()["indexed_count"] >= 1


def test_malformed_query_returns_200_not_500(client: TestClient) -> None:
    resp = client.get("/api/recall/search", params={"q": '"unterminated AND OR (((('})
    assert resp.status_code == 200


def test_archived_record_no_longer_surfaces_over_http(client: TestClient) -> None:
    record_id = _create_life_task(client, "archivemetoken task")
    assert client.get("/api/recall/search", params={"q": "archivemetoken"}).json()["results"]
    client.post(f"/api/records/{record_id}/archive")
    assert client.get("/api/recall/search", params={"q": "archivemetoken"}).json()["results"] == []
