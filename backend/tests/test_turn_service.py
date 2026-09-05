from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.models import AgentRun, Conversation, Domain, Message
from app.providers.base import ProviderError, ProviderErrorCode
from app.turn_service import ConversationNotFoundError, send_turn
from tests.conftest import FakeProvider


@pytest.fixture()
def session(populated_settings: Settings):
    engine = build_engine(populated_settings.database_url)
    session_factory = build_sessionmaker(engine)
    with session_factory() as session:
        yield session
    engine.dispose()


def _body_conversation_id(session: Session) -> str:
    domain = session.query(Domain).filter_by(slug="body").one()
    return session.query(Conversation).filter_by(domain_id=domain.id).one().id


def test_turn_creation_and_success(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)

    outcome = send_turn(
        session, fake_provider, populated_settings, conv_id, "How's my knee?", "key-1"
    )

    assert outcome.run.status == "succeeded"
    assert outcome.user_message.role == "user"
    assert outcome.user_message.content == "How's my knee?"
    assert outcome.assistant_message is not None
    assert outcome.assistant_message.role == "assistant"
    assert outcome.assistant_message.content == fake_provider.response_content


def test_user_and_assistant_messages_persisted(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    send_turn(session, fake_provider, populated_settings, conv_id, "note this", "key-2")

    messages = session.query(Message).filter_by(conversation_id=conv_id).all()
    roles = sorted(m.role for m in messages)
    assert "user" in roles
    assert "assistant" in roles


def test_provider_and_model_metadata_recorded(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-3")

    assert outcome.run.provider == "fake"
    assert outcome.run.model == populated_settings.hermes_model
    assert outcome.assistant_message.model_used == fake_provider.model


def test_token_and_latency_recorded(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-4")

    assert outcome.run.input_tokens == fake_provider.usage_input_tokens
    assert outcome.run.output_tokens == fake_provider.usage_output_tokens
    assert outcome.run.total_tokens == fake_provider.usage_total_tokens
    assert outcome.run.latency_ms == 42
    assert outcome.run.external_run_id == fake_provider.external_run_id


def test_idempotent_duplicate_request_does_not_call_provider_twice(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    key = str(uuid.uuid4())

    first = send_turn(session, fake_provider, populated_settings, conv_id, "hi", key)
    second = send_turn(session, fake_provider, populated_settings, conv_id, "hi", key)

    assert first.run.id == second.run.id
    assert len(fake_provider.sent_messages) == 1  # provider only ever called once

    run_count = session.query(AgentRun).filter_by(idempotency_key=key).count()
    assert run_count == 1


def test_bounded_context_uses_only_recent_messages(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    populated_settings.hermes_max_context_messages = 2

    for i in range(5):
        session.add(Message(conversation_id=conv_id, role="user", content=f"old message {i}"))
    session.commit()

    send_turn(session, fake_provider, populated_settings, conv_id, "the new one", "key-bounded")

    sent = fake_provider.sent_messages[0]
    assert len(sent) == 2
    assert sent[-1].content == "the new one"


def test_no_cross_domain_conversation_leakage(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    build_domain = session.query(Domain).filter_by(slug="build").one()
    build_conv = session.query(Conversation).filter_by(domain_id=build_domain.id).one()

    body_conv_id = _body_conversation_id(session)
    send_turn(session, fake_provider, populated_settings, body_conv_id, "body only", "key-body")

    sent_contents = [m.content for m in fake_provider.sent_messages[0]]
    assert "Shipped the tokenizer fix." not in sent_contents  # BUILD's pre-existing message

    build_messages = session.query(Message).filter_by(conversation_id=build_conv.id).all()
    assert all(m.content != "body only" for m in build_messages)


def test_provider_failure_preserves_user_message(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    conv_id = _body_conversation_id(session)
    fake_provider.error = ProviderError(ProviderErrorCode.TIMEOUT, "timed out")

    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "will fail", "key-fail")

    assert outcome.run.status == "failed"
    assert outcome.assistant_message is None
    assert outcome.user_message.content == "will fail"

    stored = session.query(Message).filter_by(id=outcome.user_message.id).one()
    assert stored.content == "will fail"


def test_failed_run_contains_only_sanitised_error(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderError(ProviderErrorCode.AUTH_FAILED, "Hermes rejected credentials.")
    conv_id = _body_conversation_id(session)

    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-auth-fail")

    assert outcome.run.error_code == ProviderErrorCode.AUTH_FAILED
    assert outcome.run.error_summary == "Hermes rejected credentials."
    assert "secret" not in outcome.run.error_summary.lower()
    assert "bearer" not in outcome.run.error_summary.lower()


def test_timeout_error_recorded(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderError(ProviderErrorCode.TIMEOUT, "Hermes did not respond in time.")
    conv_id = _body_conversation_id(session)

    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-timeout")
    assert outcome.run.status == "failed"
    assert outcome.run.error_code == ProviderErrorCode.TIMEOUT


def test_authentication_failure_recorded(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderError(ProviderErrorCode.AUTH_FAILED, "auth failed")
    conv_id = _body_conversation_id(session)

    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-auth2")
    assert outcome.run.status == "failed"
    assert outcome.run.error_code == ProviderErrorCode.AUTH_FAILED


def test_malformed_response_recorded(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    fake_provider.error = ProviderError(ProviderErrorCode.MALFORMED_RESPONSE, "could not parse")
    conv_id = _body_conversation_id(session)

    outcome = send_turn(session, fake_provider, populated_settings, conv_id, "hi", "key-malformed")
    assert outcome.run.status == "failed"
    assert outcome.run.error_code == ProviderErrorCode.MALFORMED_RESPONSE


def test_conversation_not_found_raises(
    session: Session, populated_settings: Settings, fake_provider: FakeProvider
) -> None:
    with pytest.raises(ConversationNotFoundError):
        send_turn(
            session,
            fake_provider,
            populated_settings,
            "00000000-0000-4000-8000-000000000000",
            "hi",
            "key-missing",
        )
