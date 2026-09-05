from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.providers.base import ProviderError, ProviderErrorCode
from tests.conftest import FakeProvider


def _domain_id(client: TestClient, slug: str) -> str:
    domains = client.get("/api/domains").json()
    return next(d["id"] for d in domains if d["slug"] == slug)


def _conversation_id(client: TestClient, slug: str) -> str:
    resp = client.post(f"/api/domains/{slug}/conversations", json={"title": "T"})
    return resp.json()["id"]


def test_turn_produces_context_snapshot(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": body_id, "kind": "health_context", "title": "Knee issue", "content": "knee pain history"},
    )
    conv_id = _conversation_id(client, "body")

    resp = client.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "What about my knee?", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    snapshot_id = resp.json()["context_snapshot_id"]
    assert snapshot_id is not None

    snapshot = client.get(f"/api/agent-runs/{run_id}/context").json()
    assert snapshot["id"] == snapshot_id
    assert snapshot["active_domain_id"] == body_id
    assert snapshot["retrieval_query"] == "What about my knee?"
    assert snapshot["estimated_context_chars"] > 0


def test_provider_receives_only_constructed_bounded_context(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    build_id = _domain_id(client, "build")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": build_id, "kind": "fact", "title": "Build secret", "content": "unrelated build info"},
    )
    conv_id = _conversation_id(client, "body")

    client.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "hi", "idempotency_key": str(uuid.uuid4())},
    )

    assert len(fake_provider.sent_system_prompts) == 1
    prompt = fake_provider.sent_system_prompts[0]
    assert "Build secret" not in prompt
    assert "unrelated build info" not in prompt


def test_explicit_additional_domain_via_api(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    client = client_with_fake_provider
    body_id = _domain_id(client, "body")
    mind_id = _domain_id(client, "mind")
    client.post(
        "/api/memories",
        json={"scope": "domain", "domain_id": mind_id, "kind": "fact", "title": "Motivation note", "content": "low motivation lately"},
    )
    conv_id = _conversation_id(client, "body")

    resp = client.post(
        f"/api/conversations/{conv_id}/turns",
        json={
            "content": "how does motivation relate to knee",
            "idempotency_key": str(uuid.uuid4()),
            "additional_domain_ids": [mind_id],
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    snapshot = client.get(f"/api/agent-runs/{run_id}/context").json()
    assert snapshot["additional_domain_ids"] == [mind_id]

    prompt = fake_provider.sent_system_prompts[0]
    assert "Motivation note" in prompt


def test_invalid_additional_domain_fails_safely_before_model_call(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    client = client_with_fake_provider
    conv_id = _conversation_id(client, "body")

    resp = client.post(
        f"/api/conversations/{conv_id}/turns",
        json={
            "content": "hi",
            "idempotency_key": str(uuid.uuid4()),
            "additional_domain_ids": ["00000000-0000-4000-8000-000000000000"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "context_build_failed"
    assert body["context_snapshot_id"] is None
    # No model call was made.
    assert len(fake_provider.sent_system_prompts) == 0


def test_provider_failure_after_context_built_preserves_snapshot(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    client = client_with_fake_provider
    fake_provider.error = ProviderError(ProviderErrorCode.UNAVAILABLE, "down")
    conv_id = _conversation_id(client, "body")

    resp = client.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "hi", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "failed"
    assert body["context_snapshot_id"] is not None

    snapshot = client.get(f"/api/agent-runs/{body['run_id']}/context")
    assert snapshot.status_code == 200


def test_ordinary_note_saving_creates_no_memory(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    conv_id = _conversation_id(client, "body")
    client.post(
        f"/api/conversations/{conv_id}/messages", json={"role": "user", "content": "just chatting, nothing special"}
    )
    memories = client.get("/api/memories").json()
    assert memories == []
