"""Regression tests for conversation-turn failure handling.

Before the fix, a Hermes reply with `content: null` crashed the request
with a 500, left the agent run stuck in 'running' forever (nothing swept it
at startup), and a retry with the same idempotency key returned 'running'
with no error, while the UI told the user their message was not sent even
though it had been saved. These tests check the saved rows directly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.base import ProviderError, ProviderErrorCode
from app.providers.hermes import HermesProvider


def _hermes_reply(monkeypatch: pytest.MonkeyPatch, payload) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: payload),
    )


def _provider() -> HermesProvider:
    return HermesProvider(base_url="http://127.0.0.1:8642", bearer_token="t", model="label")


@pytest.mark.parametrize(
    "message",
    [{"role": "assistant", "content": None}, {"role": "assistant", "content": "   "}, {"role": "assistant"}],
)
def test_hermes_null_or_blank_content_is_an_empty_response_error(monkeypatch, message) -> None:
    _hermes_reply(monkeypatch, {"choices": [{"message": message}]})
    with pytest.raises(ProviderError) as exc:
        _provider().send_turn(system_prompt="s", messages=[], timeout=1)
    assert exc.value.code == ProviderErrorCode.EMPTY_RESPONSE


@pytest.mark.parametrize("payload", [{"choices": []}, {"choices": [{"message": {"content": 5}}]}, {"nope": 1}])
def test_hermes_malformed_payloads_are_malformed_errors(monkeypatch, payload) -> None:
    _hermes_reply(monkeypatch, payload)
    with pytest.raises(ProviderError) as exc:
        _provider().send_turn(system_prompt="s", messages=[], timeout=1)
    assert exc.value.code == ProviderErrorCode.MALFORMED_RESPONSE


def test_hermes_text_parts_are_joined(monkeypatch) -> None:
    _hermes_reply(
        monkeypatch,
        {"choices": [{"message": {"content": [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]}}]},
    )
    assert _provider().send_turn(system_prompt="s", messages=[], timeout=1).content == "Hello"


def _conversation(client: TestClient) -> str:
    r = client.post("/api/domains/build/conversations", json={"title": "t"})
    assert r.status_code == 201
    return r.json()["id"]


def _rows(data_dir: Path, sql: str, *args) -> list[tuple]:
    conn = sqlite3.connect(str(data_dir / "database" / "jarvis.sqlite"))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _turn(client: TestClient, conversation_id: str, key: str, content: str = "hello"):
    return client.post(
        f"/api/conversations/{conversation_id}/turns",
        json={"content": content, "idempotency_key": key, "additional_domain_ids": []},
    )


def test_provider_failure_then_same_key_retry_reuses_the_saved_message(
    client_with_fake_provider: TestClient, fake_provider, data_dir: Path
) -> None:
    conversation_id = _conversation(client_with_fake_provider)
    fake_provider.error = ProviderError(ProviderErrorCode.EMPTY_RESPONSE, "Hermes returned an empty reply.")

    first = _turn(client_with_fake_provider, conversation_id, "k1")
    assert first.status_code == 201
    assert first.json()["status"] == "failed"
    assert first.json()["error"]["code"] == "empty_response"

    fake_provider.error = None
    retry = _turn(client_with_fake_provider, conversation_id, "k1")
    assert retry.json()["status"] == "succeeded"
    assert retry.json()["user_message"]["id"] == first.json()["user_message"]["id"]

    roles = [r[0] for r in _rows(data_dir, "SELECT role FROM messages WHERE conversation_id=? ORDER BY created_at", conversation_id)]
    assert roles == ["user", "assistant"]
    runs = _rows(data_dir, "SELECT status FROM agent_runs WHERE conversation_id=?", conversation_id)
    assert runs == [("succeeded",)]

    # A further repeat of a succeeded key never calls the provider again.
    calls = len(fake_provider.sent_messages)
    again = _turn(client_with_fake_provider, conversation_id, "k1")
    assert again.json()["status"] == "succeeded"
    assert len(fake_provider.sent_messages) == calls


def test_unexpected_provider_bug_is_recorded_as_failed_not_left_running(
    client_with_fake_provider: TestClient, fake_provider, data_dir: Path
) -> None:
    conversation_id = _conversation(client_with_fake_provider)
    fake_provider.response_content = None  # a provider that breaks the TurnResult contract

    r = _turn(client_with_fake_provider, conversation_id, "k2")
    assert r.status_code == 201
    assert r.json()["status"] == "failed"
    assert r.json()["error"]["code"] == "internal_error"
    assert _rows(data_dir, "SELECT status FROM agent_runs WHERE conversation_id=?", conversation_id) == [("failed",)]
    assert _rows(data_dir, "SELECT role FROM messages WHERE conversation_id=?", conversation_id) == [("user",)]


def test_run_left_running_by_a_dead_process_is_failed_at_startup(
    restart_client_factory, data_dir: Path
) -> None:
    first = restart_client_factory()
    conversation_id = _conversation(first)
    conn = sqlite3.connect(str(data_dir / "database" / "jarvis.sqlite"))
    try:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES ('m1', ?, 'user', 'hi', CURRENT_TIMESTAMP)",
            (conversation_id,),
        )
        conn.execute(
            "INSERT INTO agent_runs (id, conversation_id, user_message_id, provider, model, status, started_at, idempotency_key)"
            " VALUES ('r1', ?, 'm1', 'hermes', 'x', 'running', CURRENT_TIMESTAMP, 'k3')",
            (conversation_id,),
        )
        conn.commit()
    finally:
        conn.close()

    restart_client_factory()
    status, code = _rows(data_dir, "SELECT status, error_code FROM agent_runs WHERE id='r1'")[0]
    assert (status, code) == ("failed", "interrupted")


def test_concurrent_first_attempts_with_one_key_save_one_message(
    client_with_fake_provider: TestClient, data_dir: Path
) -> None:
    import threading

    conversation_id = _conversation(client_with_fake_provider)
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def go() -> None:
        barrier.wait()
        statuses.append(_turn(client_with_fake_provider, conversation_id, "same").status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [201, 201]
    assert len(_rows(data_dir, "SELECT id FROM messages WHERE role='user' AND conversation_id=?", conversation_id)) == 1
    assert len(_rows(data_dir, "SELECT id FROM agent_runs WHERE conversation_id=?", conversation_id)) == 1
