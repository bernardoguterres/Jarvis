"""Phase 10B: controller-owned proactive routines — the pure logic layer.
Every test uses an injected fake clock and fake/locally-seeded data; none
ever touches Google, the real Keychain, Hermes, or makes a model call."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app import routine_service
from app.models import Domain
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.models_memory import StructuredRecord
from app.models_routines import RoutineRun, RoutineSchedule


def _fixed_clock(t: datetime):
    return lambda: t


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


# --- Defaults / configuration ------------------------------------------


def test_routine_schedules_disabled_by_default(db_session: Session) -> None:
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        schedule = routine_service.get_or_create_schedule(db_session, routine_type)
        assert schedule.enabled is False


def test_enable_disable_schedule(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
    schedule = routine_service.set_schedule(
        db_session, "morning_briefing", enabled=True, local_time="08:00", timezone_name="Europe/Lisbon",
        weekday=None, selected_domains=[], clock=_fixed_clock(now),
    )
    assert schedule.enabled is True
    assert schedule.next_due_at is not None

    schedule2 = routine_service.set_schedule(
        db_session, "morning_briefing", enabled=False, local_time="08:00", timezone_name="Europe/Lisbon",
        weekday=None, selected_domains=[], clock=_fixed_clock(now),
    )
    assert schedule2.enabled is False
    assert schedule2.next_due_at is None


def test_invalid_local_time_rejected(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(routine_service.RoutineValidationError):
        routine_service.set_schedule(
            db_session, "morning_briefing", enabled=True, local_time="25:00", timezone_name="UTC",
            weekday=None, selected_domains=[], clock=_fixed_clock(now),
        )


def test_invalid_domain_rejected(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(routine_service.RoutineValidationError):
        routine_service.set_schedule(
            db_session, "weekly_review", enabled=True, local_time="09:00", timezone_name="UTC",
            weekday=6, selected_domains=["not_a_real_domain"], clock=_fixed_clock(now),
        )


# --- Timezone / DST -------------------------------------------------------


def test_next_occurrence_same_day_if_not_yet_passed() -> None:
    now = datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc)  # 06:00 UTC
    next_due = routine_service._next_occurrence_utc(now, "08:00", "UTC", None)
    assert next_due == datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


def test_next_occurrence_rolls_to_tomorrow_if_already_passed() -> None:
    now = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)  # past 08:00
    next_due = routine_service._next_occurrence_utc(now, "08:00", "UTC", None)
    assert next_due == datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)


def test_weekly_review_picks_correct_next_weekday() -> None:
    # 2026-08-27 is a Thursday (weekday=3). Ask for Sunday (weekday=6).
    now = datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc)
    next_due = routine_service._next_occurrence_utc(now, "09:00", "UTC", 6)
    assert next_due.astimezone(ZoneInfo("UTC")).date() == date(2026, 8, 30)
    assert next_due.weekday() == 6


def test_lisbon_dst_transition_handled_correctly() -> None:
    """Europe/Lisbon moves clocks back on the last Sunday of October. A
    schedule for 08:00 local time must still compute a UTC instant that is
    genuinely 08:00 local, on both sides of the transition."""
    before_dst_end = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)  # still BST/WEST (+1)
    after_dst_end = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)  # back to WET (+0)

    due_before = routine_service._next_occurrence_utc(before_dst_end, "08:00", "Europe/Lisbon", None)
    due_after = routine_service._next_occurrence_utc(after_dst_end, "08:00", "Europe/Lisbon", None)

    due_before_local = due_before.astimezone(ZoneInfo("Europe/Lisbon"))
    due_after_local = due_after.astimezone(ZoneInfo("Europe/Lisbon"))
    assert due_before_local.strftime("%H:%M") == "08:00"
    assert due_after_local.strftime("%H:%M") == "08:00"
    # The actual UTC offset differs across the transition (summer vs winter time) —
    # confirming the computation genuinely tracked local wall-clock time through DST,
    # not a fixed offset from UTC.
    assert due_before_local.utcoffset() != due_after_local.utcoffset()


# --- Due-time / catch-up --------------------------------------------------


def test_ordinary_scheduled_run_advances_next_due_at(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 7, 59, tzinfo=timezone.utc)
    routine_service.set_schedule(
        db_session, "morning_briefing", enabled=True, local_time="08:00", timezone_name="UTC",
        weekday=None, selected_domains=[], clock=_fixed_clock(t0),
    )
    t1 = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)
    runs = routine_service.tick(db_session, _fixed_clock(t1))
    assert len(runs) == 1
    assert runs[0].trigger == "scheduled"
    assert runs[0].outcome == "succeeded"

    schedule = db_session.get(RoutineSchedule, "morning_briefing")
    assert schedule.next_due_at.replace(tzinfo=timezone.utc) == datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc)


def test_not_yet_due_is_skipped_by_tick(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 6, 0, tzinfo=timezone.utc)
    routine_service.set_schedule(
        db_session, "morning_briefing", enabled=True, local_time="08:00", timezone_name="UTC",
        weekday=None, selected_domains=[], clock=_fixed_clock(t0),
    )
    runs = routine_service.tick(db_session, _fixed_clock(t0))
    assert runs == []


def test_exactly_one_startup_catchup_when_overdue(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = routine_service.get_or_create_schedule(db_session, "morning_briefing")
    schedule.enabled = True
    schedule.next_due_at = t0 - timedelta(days=5)  # very overdue
    db_session.commit()

    runs = routine_service.startup_catchup(db_session, _fixed_clock(t0))
    assert len(runs) == 1
    assert runs[0].trigger == "startup_catchup"


def test_no_replay_storm_after_long_downtime(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = routine_service.get_or_create_schedule(db_session, "morning_briefing")
    schedule.enabled = True
    schedule.next_due_at = t0 - timedelta(days=30)  # a month of missed mornings
    db_session.commit()

    runs = routine_service.startup_catchup(db_session, _fixed_clock(t0))
    assert len(runs) == 1

    # Immediately calling it again must not re-trigger.
    runs2 = routine_service.startup_catchup(db_session, _fixed_clock(t0))
    assert runs2 == []


def test_duplicate_prevention_across_rapid_restarts(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = routine_service.get_or_create_schedule(db_session, "morning_briefing")
    schedule.enabled = True
    schedule.next_due_at = t0 - timedelta(hours=1)
    db_session.commit()

    routine_service.startup_catchup(db_session, _fixed_clock(t0))
    routine_service.startup_catchup(db_session, _fixed_clock(t0 + timedelta(seconds=5)))
    routine_service.startup_catchup(db_session, _fixed_clock(t0 + timedelta(seconds=10)))

    count = db_session.query(RoutineRun).filter(RoutineRun.routine_type == "morning_briefing").count()
    assert count == 1


# --- Single-flight ----------------------------------------------------------


def test_manual_and_scheduled_cannot_overlap(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    acquired = routine_service.try_acquire_routine_lock("morning_briefing")
    assert acquired is True
    try:
        run = routine_service.run_routine(db_session, "morning_briefing", "manual", _fixed_clock(t0))
        assert run.outcome == "skipped"
    finally:
        routine_service.release_routine_lock("morning_briefing")


# --- Domain consent / sensitivity isolation -------------------------------


def test_sensitive_domains_excluded_unless_explicitly_selected(db_session: Session) -> None:
    mind_id = _domain_id(db_session, "mind")
    db_session.add(
        StructuredRecord(
            domain_id=mind_id, record_type="mind_checkin", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"mood": "anxious", "note": "private"}),
        )
    )
    db_session.commit()

    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    sections = routine_service.build_morning_briefing(db_session, selected_domains=[], today=t0.date())
    all_text = json.dumps([{"title": s.title, "lines": [l.text for l in s.lines]} for s in sections])
    assert "anxious" not in all_text
    assert "MIND" not in all_text.upper() or not any("mood" in l for s in sections for l in [ln.text for ln in s.lines])


def test_sensitive_domain_included_when_explicitly_selected(db_session: Session) -> None:
    mind_id = _domain_id(db_session, "mind")
    db_session.add(
        StructuredRecord(
            domain_id=mind_id, record_type="mind_checkin", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"mood": "calm", "note": "fine"}),
        )
    )
    db_session.commit()

    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    sections = routine_service.build_morning_briefing(db_session, selected_domains=["mind"], today=t0.date())
    all_text = " ".join(l.text for s in sections for l in s.lines)
    assert "calm" in all_text


# --- Deterministic source references ---------------------------------------


def test_morning_briefing_has_deterministic_source_references(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    record = StructuredRecord(
        domain_id=life_id, record_type="life_task", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": "Renew passport", "due_date": "2026-09-01"}),
    )
    db_session.add(record)
    db_session.commit()

    sections = routine_service.build_morning_briefing(db_session, selected_domains=[], today=date(2026, 8, 27))
    life_section = next(s for s in sections if "LIFE" in s.title)
    assert len(life_section.lines) == 1
    assert life_section.lines[0].source_ref == f"record:{record.id[:8]}"
    assert "Renew passport" in life_section.lines[0].text


def test_evening_checkin_is_a_fixed_template_no_data_pulled() -> None:
    sections = routine_service.build_evening_checkin()
    assert len(sections) == 1
    assert len(sections[0].lines) == 4


def test_calendar_section_only_shows_todays_selected_calendar_events(db_session: Session) -> None:
    calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
    db_session.add(calendar)
    db_session.flush()
    today = date(2026, 8, 27)
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev1", title="Dentist", all_day=False,
            start_datetime=datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc),
        )
    )
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev2", title="Next week", all_day=False,
            start_datetime=datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()

    sections = routine_service.build_morning_briefing(db_session, selected_domains=[], today=today)
    cal_section = next(s for s in sections if "Calendar" in s.title)
    assert len(cal_section.lines) == 1
    assert "Dentist" in cal_section.lines[0].text


# --- History retention -----------------------------------------------------


def test_bounded_history_retention(db_session: Session) -> None:
    from app.models_routines import ROUTINE_RUN_RETENTION_PER_TYPE

    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    for i in range(ROUTINE_RUN_RETENTION_PER_TYPE + 5):
        routine_service.run_routine(db_session, "morning_briefing", "manual", _fixed_clock(t0 + timedelta(minutes=i)))

    count = db_session.query(RoutineRun).filter(RoutineRun.routine_type == "morning_briefing").count()
    assert count == ROUTINE_RUN_RETENTION_PER_TYPE


def test_no_secrets_or_credentials_in_routine_output(db_session: Session) -> None:
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    run = routine_service.run_routine(db_session, "morning_briefing", "manual", _fixed_clock(t0))
    assert run.output_json is not None
    assert "access_token" not in run.output_json
    assert "refresh_token" not in run.output_json
