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


def test_general_conversation_never_leaks_sensitive_domain_documents(
    db_session: Session, memory_settings: Settings
) -> None:
    """Regression for a real leak: a general (domain=None) conversation's
    in-scope domain list resolves to [], and document search must treat an
    explicit empty scope as "zero domains," never silently fall back to
    "no filter" (which would surface MIND/PEOPLE document content in an
    unrelated conversation)."""
    mind = db_session.query(Domain).filter_by(slug="mind").one()
    document_service.import_document(
        db_session,
        memory_settings,
        domain_id=mind.id,
        original_filename="diary.txt",
        data=b"Feeling anxious about the relationship and therapy session notes.",
    )
    conv = Conversation(domain_id=None, title="general")
    db_session.add(conv)
    db_session.commit()

    package = context_builder.build_context(
        db_session,
        conversation=conv,
        domain=None,
        additional_domain_ids=[],
        query_text="anxious therapy session",
        max_recent_messages=5,
    )
    assert "Cited document excerpts" not in package.system_prompt
    assert "anxious" not in package.system_prompt
    assert package.snapshot.document_chunk_ids == []


def test_general_conversation_document_leak_fixed_but_explicit_domain_still_works(
    db_session: Session, memory_settings: Settings
) -> None:
    """Sanity check alongside the regression above: explicitly adding MIND
    as an additional domain still surfaces its documents as intended:
    the fix must narrow an implicit empty scope, not break explicit scope."""
    mind = db_session.query(Domain).filter_by(slug="mind").one()
    life = db_session.query(Domain).filter_by(slug="life").one()
    document_service.import_document(
        db_session,
        memory_settings,
        domain_id=mind.id,
        original_filename="diary.txt",
        data=b"Feeling anxious about the relationship and therapy session notes.",
    )
    conv = Conversation(domain_id=life.id, title="life convo")
    db_session.add(conv)
    db_session.commit()

    package = context_builder.build_context(
        db_session,
        conversation=conv,
        domain=life,
        additional_domain_ids=[mind.id],
        query_text="anxious therapy session",
        max_recent_messages=5,
    )
    assert len(package.snapshot.document_chunk_ids) >= 1
    assert "Cited document excerpts" in package.system_prompt


def test_general_conversation_gets_google_health_only_when_body_is_added(db_session: Session) -> None:
    """D119: a Home voice question about health adds BODY to that one
    general turn, and that alone is what brings Google Health data in. A
    general turn without BODY still gets none of it."""
    _connect(db_session, "google_health")
    db_session.add(GoogleHealthDailySummary(date=date.today(), steps=4321, sleep_minutes_asleep=402))
    db_session.commit()
    body = db_session.query(Domain).filter_by(slug="body").one()
    conv = Conversation(domain_id=None, title="Home voice")
    db_session.add(conv)
    db_session.commit()

    without = context_builder.build_context(
        db_session, conversation=conv, domain=None, additional_domain_ids=[], query_text="how did I sleep", max_recent_messages=5
    )
    assert "Google Health" not in without.system_prompt
    assert without.snapshot.google_health_summary_ids == []

    with_body = context_builder.build_context(
        db_session, conversation=conv, domain=None, additional_domain_ids=[body.id], query_text="how did I sleep", max_recent_messages=5
    )
    assert "BODY — Google Health data" in with_body.system_prompt
    assert "steps=4321" in with_body.system_prompt and "sleep_min=402" in with_body.system_prompt
    assert len(with_body.snapshot.google_health_summary_ids) == 1
    assert with_body.snapshot.additional_domain_ids == [body.id]


def test_body_context_reports_older_latest_values_and_latest_run(db_session: Session) -> None:
    """D120: a weigh-in older than the last few days is still reported with
    its date, and the latest run (with distance) is reported even when more
    recent walks fill the recent-sessions list."""
    _connect(db_session, "google_health")
    today = date.today()
    for offset in range(3):
        db_session.add(GoogleHealthDailySummary(date=today - timedelta(days=offset), steps=10000 + offset, heart_rate_avg_bpm=77.557))
    db_session.add(GoogleHealthDailySummary(date=today - timedelta(days=40), weight_kg=70.04))
    now = datetime.now(timezone.utc)
    db_session.add(
        GoogleHealthSession(
            session_type="exercise", external_id="run-1", activity_type="Run",
            start_time=now - timedelta(days=5, minutes=49), end_time=now - timedelta(days=5), distance_km=9.66,
        )
    )
    for i in range(5):
        db_session.add(
            GoogleHealthSession(
                session_type="exercise", external_id=f"walk-{i}", activity_type="Walk",
                start_time=now - timedelta(days=i, minutes=30), end_time=now - timedelta(days=i), distance_km=2.0,
            )
        )
    db_session.commit()
    body = db_session.query(Domain).filter_by(slug="body").one()

    package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="how far was my last run", max_recent_messages=5
    )
    prompt = package.system_prompt
    assert f"weight_kg=70.0 (recorded {(today - timedelta(days=40)).isoformat()})" in prompt
    assert "Latest session of each other activity type:" in prompt
    assert "(Run, 49m, 9.66 km)" in prompt
    assert "hr_avg=78" in prompt and "hr_avg=77.5" not in prompt
    # The older weigh-in's summary is recorded in the snapshot for audit.
    assert len(package.snapshot.google_health_summary_ids) == 4


def test_body_context_omits_older_values_already_shown(db_session: Session) -> None:
    _connect(db_session, "google_health")
    db_session.add(GoogleHealthDailySummary(date=date.today(), steps=5000, weight_kg=71.2))
    db_session.commit()
    body = db_session.query(Domain).filter_by(slug="body").one()
    package = context_builder.build_context(
        db_session, conversation=_conversation(db_session, body), domain=body, additional_domain_ids=[], query_text="q", max_recent_messages=5
    )
    assert "weight_kg=71.2" in package.system_prompt
    assert "Most recent value of metrics" not in package.system_prompt
    assert "Latest session of each other activity type" not in package.system_prompt


def _fixed_local_now(monkeypatch, when: datetime) -> None:
    monkeypatch.setattr(context_builder, "_local_now", lambda: when)


def test_calendar_context_orders_by_start_and_includes_earlier_today(db_session: Session, monkeypatch) -> None:
    """D121: all-day and timed events are interleaved by start, events from
    earlier today are kept, times are shown in local time with weekday and
    end time, and the model is told the current date."""
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    now_local = datetime(2026, 11, 20, 20, 0, tzinfo=london)
    _fixed_local_now(monkeypatch, now_local)
    _connect(db_session, "google_calendar")
    cal = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
    db_session.add(cal)
    db_session.flush()
    utc = timezone.utc
    db_session.add_all([
        CalendarEventCache(calendar_id=cal.id, external_event_id="far-all-day", title="Far holiday", all_day=True,
                           start_date=date(2026, 12, 1), end_date=date(2026, 12, 2)),
        CalendarEventCache(calendar_id=cal.id, external_event_id="this-morning", title="Morning class", all_day=False,
                           start_datetime=datetime(2026, 11, 20, 10, 0, tzinfo=utc), end_datetime=datetime(2026, 11, 20, 12, 0, tzinfo=utc)),
        CalendarEventCache(calendar_id=cal.id, external_event_id="tomorrow", title="Breakfast", all_day=False,
                           start_datetime=datetime(2026, 11, 21, 8, 30, tzinfo=utc), end_datetime=datetime(2026, 11, 21, 9, 30, tzinfo=utc)),
        CalendarEventCache(calendar_id=cal.id, external_event_id="yesterday", title="Old event", all_day=False,
                           start_datetime=datetime(2026, 11, 19, 10, 0, tzinfo=utc), end_datetime=datetime(2026, 11, 19, 11, 0, tzinfo=utc)),
    ])
    db_session.commit()
    life = db_session.query(Domain).filter_by(slug="life").one()

    prompt = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[], query_text="what's on", max_recent_messages=5
    ).system_prompt

    assert "Current local date and time: Friday 20 November 2026, 20:00 (GMT)." in prompt
    assert "Old event" not in prompt
    morning = prompt.index("Fri 2026-11-20 10:00-12:00: Morning class")
    breakfast = prompt.index("Sat 2026-11-21 08:30-09:30: Breakfast")
    holiday = prompt.index("Tue 2026-12-01 (all day): Far holiday")
    assert morning < breakfast < holiday


def test_calendar_context_excludes_unselected_calendars(db_session: Session) -> None:
    _connect(db_session, "google_calendar")
    hidden = CalendarCalendar(external_calendar_id="other", summary="Other", access_role="reader", is_owned=False, selected=False)
    db_session.add(hidden)
    db_session.flush()
    db_session.add(CalendarEventCache(calendar_id=hidden.id, external_event_id="h1", title="Hidden calendar event", all_day=False,
                                      start_datetime=datetime.now(timezone.utc) + timedelta(days=1)))
    db_session.commit()
    life = db_session.query(Domain).filter_by(slug="life").one()
    prompt = context_builder.build_context(
        db_session, conversation=_conversation(db_session, life), domain=life, additional_domain_ids=[], query_text="q", max_recent_messages=5
    ).system_prompt
    assert "Hidden calendar event" not in prompt


def test_calendar_event_times_are_stored_as_utc() -> None:
    """D121: a summer time with an offset is converted to UTC before it is
    stored, since SQLite drops the offset and readers treat it as UTC."""
    from app.providers.google_calendar import _normalize_event

    event = _normalize_event({
        "id": "e1", "summary": "Summer dinner",
        "start": {"dateTime": "2026-07-01T19:00:00+01:00"},
        "end": {"dateTime": "2026-07-01T21:00:00+01:00"},
    })
    assert event.start_datetime == datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)
    assert event.end_datetime.utcoffset() == timedelta(0)
