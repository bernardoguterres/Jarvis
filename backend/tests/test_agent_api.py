from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.providers.base import ProviderError, ProviderErrorCode
from tests.conftest import FakeProvider


def _create_conversation(client: TestClient, slug: str = "body") -> str:
    resp = client.post(f"/api/domains/{slug}/conversations", json={"title": "T"})
    return resp.json()["id"]


def test_turn_success(client_with_fake_provider: TestClient) -> None:
    client = client_with_fake_provider
    conv_id = _create_conversation(client)

    resp = client.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "How's my knee?", "idempotency_key": str(uuid.uuid4())},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["user_message"]["content"] == "How's my knee?"
    assert body["assistant_message"]["content"]
    assert body["provider"] == "fake"
    assert body["usage"]["total_tokens"] is not None
    assert body["error"] is None


def test_turn_invalid_conversation_returns_404(client_with_fake_provider: TestClient) -> None:
    resp = client_with_fake_provider.post(
        "/api/conversations/00000000-0000-4000-8000-000000000000/turns",
        json={"content": "hi", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


def test_turn_empty_content_rejected(client_with_fake_provider: TestClient) -> None:
    conv_id = _create_conversation(client_with_fake_provider)
    resp = client_with_fake_provider.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "", "idempotency_key": str(uuid.uuid4())},
    )
    assert resp.status_code == 422


def test_turn_provider_failure_returns_sanitised_error(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderError(ProviderErrorCode.UNAVAILABLE, "Hermes is not reachable.")
    conv_id = _create_conversation(client_with_fake_provider)

    resp = client_with_fake_provider.post(
        f"/api/conversations/{conv_id}/turns",
        json={"content": "hi", "idempotency_key": str(uuid.uuid4())},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "failed"
    assert body["assistant_message"] is None
    assert body["error"]["code"] == ProviderErrorCode.UNAVAILABLE
    assert body["user_message"]["content"] == "hi"


def test_turn_idempotent_duplicate_via_api(client_with_fake_provider: TestClient) -> None:
    conv_id = _create_conversation(client_with_fake_provider)
    key = str(uuid.uuid4())

    first = client_with_fake_provider.post(
        f"/api/conversations/{conv_id}/turns", json={"content": "hi", "idempotency_key": key}
    )
    second = client_with_fake_provider.post(
        f"/api/conversations/{conv_id}/turns", json={"content": "hi", "idempotency_key": key}
    )

    assert first.json()["run_id"] == second.json()["run_id"]


def test_plain_note_saving_does_not_invoke_provider(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    conv_id = _create_conversation(client_with_fake_provider)

    resp = client_with_fake_provider.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "just a note"},
    )

    assert resp.status_code == 201
    assert len(fake_provider.sent_messages) == 0


def test_agent_status_available_and_configured(client_with_fake_provider: TestClient) -> None:
    resp = client_with_fake_provider.get("/api/agent/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hermes_available"] is True
    assert body["model_configured"] is True
    assert body["model"] == "openai-codex/gpt-5.6-terra"
    assert body["provider"] == "fake"


def test_agent_status_unavailable(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    fake_provider.available = False
    resp = client_with_fake_provider.get("/api/agent/status")
    body = resp.json()
    assert body["hermes_available"] is False
    assert body["model_configured"] is False


def test_agent_status_never_returns_bearer_token(client: TestClient) -> None:
    # Uses the REAL HermesProvider (pointed at a bearer token the test process
    # never even sets meaningfully) purely to confirm the response schema
    # cannot leak a token field, regardless of provider implementation.
    resp = client.get("/api/agent/status")
    assert resp.status_code == 200
    body_text = resp.text
    assert "bearer" not in body_text.lower()
    assert "token" not in body_text.lower()


def test_app_usable_without_hermes(
    client_with_fake_provider: TestClient, fake_provider: FakeProvider
) -> None:
    """With Hermes unavailable, plain persistence features must keep working."""
    fake_provider.available = False
    client = client_with_fake_provider

    conv_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conv_id}/messages", json={"role": "user", "content": "still works"}
    )
    assert resp.status_code == 201

    status_resp = client.get("/api/agent/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["hermes_available"] is False
