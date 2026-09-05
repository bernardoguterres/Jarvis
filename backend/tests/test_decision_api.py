"""Phase 12F: HTTP-level tests for the Decision Room endpoints. Uses the
standard `client` fixture (fake Hermes/STT/TTS already wired by
conftest.py) — every route except `POST .../briefs/critique` never calls
a model; that one is covered via `client_with_fake_provider`. Deliberately
focuses on HTTP-layer concerns (status codes, malformed input, the
PUT/POST-only method convention) rather than re-proving service-layer
behaviour already covered by test_decision_service.py."""

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


def _create_decision(client: TestClient, **overrides) -> dict:
    payload = {"title": "Which tokenizer for Alpha?"}
    payload.update(overrides)
    resp = client.post("/api/decisions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_option(client: TestClient, decision_id: str, name: str = "BPE") -> dict:
    resp = client.post(f"/api/decisions/{decision_id}/options", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- decision CRUD and lifecycle --------------------------------------------------


def test_create_and_get_decision(client: TestClient) -> None:
    d = _create_decision(client)
    resp = client.get(f"/api/decisions/{d['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"
    assert resp.json()["included_domain_slugs"] == ["life", "path", "build"]


def test_get_unknown_decision_returns_404(client: TestClient) -> None:
    resp = client.get("/api/decisions/does-not-exist")
    assert resp.status_code == 404


def test_create_decision_malformed_title_returns_422(client: TestClient) -> None:
    resp = client.post("/api/decisions", json={"title": ""})
    assert resp.status_code == 422


def test_list_decisions_status_filter(client: TestClient) -> None:
    a = _create_decision(client, title="a")
    b = _create_decision(client, title="b")
    client.post(f"/api/decisions/{b['id']}/abandon", json={})

    draft = client.get("/api/decisions", params={"status": "draft"}).json()
    abandoned = client.get("/api/decisions", params={"status": "abandoned"}).json()
    assert {x["id"] for x in draft} == {a["id"]}
    assert {x["id"] for x in abandoned} == {b["id"]}


def test_bad_status_filter_returns_400(client: TestClient) -> None:
    resp = client.get("/api/decisions", params={"status": "not-a-status"})
    assert resp.status_code == 400


def test_lifecycle_over_http_start_evaluating_decide_reopen(client: TestClient) -> None:
    d = _create_decision(client)
    option = _create_option(client, d["id"])

    resp = client.post(f"/api/decisions/{d['id']}/start-evaluating")
    assert resp.status_code == 200 and resp.json()["status"] == "evaluating"

    resp = client.post(
        f"/api/decisions/{d['id']}/decide",
        json={"selected_option_id": option["id"], "rationale": "Simplest option.", "decision_confidence": 4},
    )
    assert resp.status_code == 200 and resp.json()["status"] == "decided"

    resp = client.post(f"/api/decisions/{d['id']}/reopen")
    assert resp.status_code == 200 and resp.json()["status"] == "reopened"


def test_invalid_lifecycle_transition_returns_400(client: TestClient) -> None:
    d = _create_decision(client)
    # decide() with no options at all yet -> a clean 400, not a 500.
    resp = client.post(
        f"/api/decisions/{d['id']}/decide",
        json={"selected_option_id": "does-not-exist", "rationale": "r", "decision_confidence": 3},
    )
    assert resp.status_code == 400
    resp = client.post(f"/api/decisions/{d['id']}/reopen")  # draft cannot be reopened
    assert resp.status_code == 400


def test_editing_after_decided_returns_400(client: TestClient) -> None:
    d = _create_decision(client)
    option = _create_option(client, d["id"])
    client.post(
        f"/api/decisions/{d['id']}/decide",
        json={"selected_option_id": option["id"], "rationale": "r", "decision_confidence": 3},
    )
    resp = client.put(f"/api/decisions/{d['id']}/options/{option['id']}", json={"name": "renamed"})
    assert resp.status_code == 400


def test_supersede_over_http(client: TestClient) -> None:
    old = _create_decision(client, title="old")
    option = _create_option(client, old["id"])
    client.post(
        f"/api/decisions/{old['id']}/decide",
        json={"selected_option_id": option["id"], "rationale": "r", "decision_confidence": 3},
    )
    new = _create_decision(client, title="new")
    resp = client.post(f"/api/decisions/{old['id']}/supersede", json={"new_decision_id": new["id"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "superseded"
    assert resp.json()["superseded_by_decision_id"] == new["id"]


# --- evidence discovery, add, idempotency, privacy ------------------------------


def test_evidence_search_scoped_to_effective_policy(client: TestClient) -> None:
    d = _create_decision(client, included_domain_slugs=["life"])
    _create_life_task(client, "unique-search-marker task")
    _create_mind_record(client, "unique-search-marker mood")

    resp = client.get(f"/api/decisions/{d['id']}/evidence/search", params={"q": "unique-search-marker"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["domain_slug"] == "life"


def test_add_evidence_idempotent_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    task_id = _create_life_task(client, "task for evidence")
    first = client.post(
        f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id}
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id}
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get(f"/api/decisions/{d['id']}/evidence").json()) == 1


def test_add_evidence_sensitive_domain_default_rejected_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    mind_id = _create_mind_record(client, "anxious")
    resp = client.post(f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": mind_id})
    assert resp.status_code == 400


def test_add_evidence_malformed_source_type_returns_422(client: TestClient) -> None:
    d = _create_decision(client)
    resp = client.post(f"/api/decisions/{d['id']}/evidence", json={"source_type": "not_a_real_type", "source_id": "x"})
    assert resp.status_code == 422


def test_add_evidence_malformed_source_id_returns_clean_error(client: TestClient) -> None:
    d = _create_decision(client)
    resp = client.post(
        f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": "definitely-does-not-exist"}
    )
    assert resp.status_code == 400
    assert "detail" in resp.json()


def test_remove_evidence_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    task_id = _create_life_task(client, "task")
    evidence = client.post(f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id}).json()
    resp = client.post(f"/api/decisions/{d['id']}/evidence/{evidence['id']}/remove")
    assert resp.status_code == 200
    assert resp.json()["status"] == "removed"
    assert client.get(f"/api/decisions/{d['id']}/evidence").json() == []


# --- criteria / assessments / score breakdown -----------------------------------


def test_criteria_and_assessment_and_score_breakdown_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    opt1 = _create_option(client, d["id"], "BPE")
    opt2 = _create_option(client, d["id"], "Unigram")
    c1 = client.post(f"/api/decisions/{d['id']}/criteria", json={"name": "Simplicity", "weight": 4}).json()

    resp = client.put(f"/api/decisions/{d['id']}/assessments", json={"option_id": opt1["id"], "criterion_id": c1["id"], "score": 5})
    assert resp.status_code == 200

    resp = client.get(f"/api/decisions/{d['id']}/score-breakdown")
    body = resp.json()
    by_id = {o["option_id"]: o for o in body["options"]}
    assert by_id[opt1["id"]]["total_score"] == 20
    assert by_id[opt2["id"]]["missing_criterion_ids"] == [c1["id"]]
    assert body["incomplete"] is True


def test_remove_criterion_returns_204(client: TestClient) -> None:
    d = _create_decision(client)
    c1 = client.post(f"/api/decisions/{d['id']}/criteria", json={"name": "C", "weight": 3}).json()
    resp = client.post(f"/api/decisions/{d['id']}/criteria/{c1['id']}/remove")
    assert resp.status_code == 204
    assert client.get(f"/api/decisions/{d['id']}/criteria").json() == []


# --- factors ---------------------------------------------------------------------


def test_factor_add_and_resolve_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    factor = client.post(f"/api/decisions/{d['id']}/factors", json={"kind": "risk", "content": "Might be slower."}).json()
    resp = client.post(f"/api/decisions/{d['id']}/factors/{factor['id']}/resolve", json={"resolution_note": "Did not materialize."})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


# --- briefs ------------------------------------------------------------------------


def test_deterministic_brief_generation_and_versioning_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    _create_option(client, d["id"])
    v1 = client.post(f"/api/decisions/{d['id']}/briefs/deterministic")
    assert v1.status_code == 201
    assert v1.json()["version_number"] == 1
    v2 = client.post(f"/api/decisions/{d['id']}/briefs/deterministic")
    assert v2.json()["version_number"] == 2
    assert len(client.get(f"/api/decisions/{d['id']}/briefs").json()) == 2


def test_critique_with_jarvis_over_http_uses_fake_provider(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    d = _create_decision(client)
    _create_option(client, d["id"])
    task_id = _create_life_task(client, "evidence task")
    client.post(f"/api/decisions/{d['id']}/evidence", json={"source_type": "structured_record", "source_id": task_id})

    resp = client.post(f"/api/decisions/{d['id']}/briefs/critique")
    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "model"
    assert body["model_meta"]["provider"] == "fake"
    assert "Jarvis model-generated critique" in body["title"]


def test_critique_with_no_evidence_returns_clean_502_and_no_model_call(client_with_fake_provider: TestClient, fake_provider) -> None:
    client = client_with_fake_provider
    d = _create_decision(client)
    _create_option(client, d["id"])
    resp = client.post(f"/api/decisions/{d['id']}/briefs/critique")
    assert resp.status_code == 502
    assert fake_provider.sent_messages == []


# --- outcome review and calibration ------------------------------------------------


def test_outcome_review_over_http(client: TestClient) -> None:
    d = _create_decision(client)
    option = _create_option(client, d["id"])
    client.post(f"/api/decisions/{d['id']}/decide", json={"selected_option_id": option["id"], "rationale": "r", "decision_confidence": 3})
    resp = client.post(
        f"/api/decisions/{d['id']}/outcome-reviews",
        json={"what_happened": "Worked out fine.", "intended_outcome_achieved": True, "would_decide_same_again": True},
    )
    assert resp.status_code == 201
    assert len(client.get(f"/api/decisions/{d['id']}/outcome-reviews").json()) == 1


def test_calibration_summary_over_http_reports_insufficient_sample(client: TestClient) -> None:
    resp = client.get("/api/decisions-calibration-summary")
    assert resp.status_code == 200
    assert resp.json()["has_enough_data"] is False


def test_get_unknown_brief_version_returns_404(client: TestClient) -> None:
    d = _create_decision(client)
    resp = client.get(f"/api/decisions/{d['id']}/briefs/does-not-exist")
    assert resp.status_code == 404
