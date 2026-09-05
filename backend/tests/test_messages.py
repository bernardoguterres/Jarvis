from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import build_engine, build_sessionmaker
from app.models import Message
from app.schemas import MAX_MESSAGE_LENGTH


def _create_conversation(client: TestClient) -> str:
    resp = client.post("/api/domains/body/conversations", json={"title": "T"})
    return resp.json()["id"]


def test_create_and_retrieve_messages(client: TestClient) -> None:
    conversation_id = _create_conversation(client)

    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "Knee felt fine on today's run."},
    )
    assert resp.status_code == 201
    message = resp.json()
    assert message["role"] == "user"
    assert message["content"] == "Knee felt fine on today's run."

    resp = client.get(f"/api/conversations/{conversation_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 1
    assert messages[0]["id"] == message["id"]


def test_messages_for_invalid_conversation_returns_404(client: TestClient) -> None:
    resp = client.get("/api/conversations/00000000-0000-4000-8000-000000000000/messages")
    assert resp.status_code == 404

    resp = client.post(
        "/api/conversations/00000000-0000-4000-8000-000000000000/messages",
        json={"role": "user", "content": "hello"},
    )
    assert resp.status_code == 404


def test_invalid_role_rejected(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "villain", "content": "hello"},
    )
    assert resp.status_code == 422


def test_empty_message_rejected(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": ""},
    )
    assert resp.status_code == 422


def test_whitespace_only_message_rejected(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "   "},
    )
    assert resp.status_code == 422


def test_excessive_message_length_rejected(client: TestClient) -> None:
    conversation_id = _create_conversation(client)
    resp = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "x" * (MAX_MESSAGE_LENGTH + 1)},
    )
    assert resp.status_code == 422


def test_foreign_key_enforced_for_message_conversation(client: TestClient) -> None:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    session_factory = build_sessionmaker(engine)

    with session_factory() as session:
        session.add(
            Message(
                conversation_id="00000000-0000-4000-8000-000000000000",
                role="user",
                content="orphan message",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()
