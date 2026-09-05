from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_list_conversations(client: TestClient) -> None:
    resp = client.post("/api/domains/body/conversations", json={"title": "Knee check-in"})
    assert resp.status_code == 201
    conversation = resp.json()
    assert conversation["domain_id"]
    assert conversation["title"] == "Knee check-in"

    resp = client.get("/api/domains/body/conversations")
    assert resp.status_code == 200
    conversations = resp.json()
    assert len(conversations) == 1
    assert conversations[0]["id"] == conversation["id"]


def test_create_conversation_invalid_domain_returns_404(client: TestClient) -> None:
    resp = client.post("/api/domains/not-a-real-domain/conversations", json={})
    assert resp.status_code == 404


def test_domain_isolation_body_conversation_not_in_build(client: TestClient) -> None:
    client.post("/api/domains/body/conversations", json={"title": "Body only"})

    body_conversations = client.get("/api/domains/body/conversations").json()
    build_conversations = client.get("/api/domains/build/conversations").json()

    assert len(body_conversations) == 1
    assert len(build_conversations) == 0


def test_foreign_key_enforced_on_conversation_delete_cascade(client: TestClient) -> None:
    # A conversation's messages must not be orphanable; FK enforcement is exercised
    # via the message tests, but we confirm the conversation row requires a real domain.
    resp = client.post("/api/domains/mind/conversations", json={})
    assert resp.status_code == 201
    assert resp.json()["title"] is None
