"""Phase 9 (corrected) context-builder integration: Google Health only enters BODY context,
Google Calendar only enters LIFE context (by default), documents enter via
their assigned domain, and everything is recorded in the context snapshot
for audit."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import context_builder, document_service
from app.config import Settings
from app.models import Conversation, Domain
from app.models_integrations import (
    CalendarCalendar,
    CalendarEventCache,
    GoogleHealthDailySummary,
    GoogleHealthSession,
    IntegrationConnection,
)


def _conversation(db_session: Session, domain: Domain) -> Conversation:
    conv = Conversation(domain_id=domain.id, title="test")
    db_session.add(conv)
    db_session.commit()
    return conv


def _connect(db_session: Session, provider: str) -> None:
    db_session.add(IntegrationConnection(provider=provider, status="connected", scopes_json="[]", last_sync_at=datetime.now(timezone.utc)))
    db_session.commit()


def test_google_health_data_enters_body_context_only(db_session: Session) -> None:
    _connect(db_session, "google_health")
    db_session.add(GoogleHealthDailySummary(date=date.today(), steps=9999))
    db_session.commit()

    body = db_session.query(Domain).filter_by(slug="body").one()
    life = db_session.query(Domain).filter_by(slug="life").one()

    body_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="how am I doing", max_recent_messages=5
    )
    assert "Google Health" in body_package.system_prompt
    assert len(body_package.snapshot.google_health_summary_ids) == 1

    life_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[], query_text="what's next", max_recent_messages=5
    )
    assert "Google Health" not in life_package.system_prompt
    assert life_package.snapshot.google_health_summary_ids == []


def test_google_health_sessions_enter_body_context_only(db_session: Session) -> None:
    _connect(db_session, "google_health")
    db_session.add(
        GoogleHealthSession(
            session_type="sleep",
            external_id="sess-1",
            start_time=datetime(2026, 8, 25, 22, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 8, 26, 6, 0, tzinfo=timezone.utc),
            minutes_asleep=440,
            minutes_awake=40,
            source_platform="FITBIT",
        )
    )
    db_session.commit()

    body = db_session.query(Domain).filter_by(slug="body").one()
    life = db_session.query(Domain).filter_by(slug="life").one()

    body_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="how did I sleep", max_recent_messages=5
    )
    assert "sleep" in body_package.system_prompt
    assert "FITBIT" in body_package.system_prompt

    life_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[], query_text="what's next", max_recent_messages=5
    )
    assert "FITBIT" not in life_package.system_prompt


def test_google_health_data_included_when_body_explicitly_added(db_session: Session) -> None:
    _connect(db_session, "google_health")
    db_session.add(GoogleHealthDailySummary(date=date.today(), steps=1111))
    db_session.commit()

    life = db_session.query(Domain).filter_by(slug="life").one()
    body = db_session.query(Domain).filter_by(slug="body").one()

    package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[body.id], query_text="q", max_recent_messages=5
    )
    assert "Google Health" in package.system_prompt


def test_calendar_data_enters_life_context_only(db_session: Session) -> None:
    _connect(db_session, "google_calendar")
    calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
    db_session.add(calendar)
    db_session.flush()
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev1", title="Dentist", all_day=False,
            start_datetime=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    db_session.commit()

    life = db_session.query(Domain).filter_by(slug="life").one()
    body = db_session.query(Domain).filter_by(slug="body").one()

    life_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[], query_text="what's on", max_recent_messages=5
    )
    assert "Dentist" in life_package.system_prompt
    assert len(life_package.snapshot.calendar_event_ids) == 1

    body_package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="q", max_recent_messages=5
    )
    assert "Dentist" not in body_package.system_prompt
    assert body_package.snapshot.calendar_event_ids == []


def test_document_citation_recorded_in_snapshot(db_session: Session, memory_settings: Settings) -> None:
    body = db_session.query(Domain).filter_by(slug="body").one()
    document_service.import_document(
        db_session, memory_settings, domain_id=body.id, original_filename="knee.txt", data=b"The knee has a history of pain during running."
    )

    package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="knee pain", max_recent_messages=5
    )
    assert len(package.snapshot.document_chunk_ids) >= 1
    assert "Cited document excerpts" in package.system_prompt


def test_disconnected_integrations_produce_no_context(db_session: Session) -> None:
    # No IntegrationConnection rows at all == disconnected by default.
    db_session.add(GoogleHealthDailySummary(date=date.today(), steps=5000))
    db_session.commit()

    body = db_session.query(Domain).filter_by(slug="body").one()
    package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="q", max_recent_messages=5
    )
    assert "Google Health" not in package.system_prompt
