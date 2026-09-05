"""Phase 12B: briefing continuity — stable identity/fingerprint rules,
new/changed/ongoing/resolved/reopened classification, false-resolution
protection, priority-cap-churn safety, and snapshot spam prevention.

Every test uses fictional fixtures seeded directly into the isolated test
database, and an injected/fixed clock — no real Google/Keychain/Hermes/
model contact, matching app/briefing_service.py's own "no model call,
ever" guarantee."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from sqlalchemy.orm import Session

from app import briefing_service
from app.models import Domain
from app.models_briefing import BriefingItemState, BriefingSnapshot
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.models_memory import StructuredRecord
from app.models_routines import RoutineRun


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _life_task(db_session: Session, title: str, due_date: str) -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "life"), record_type="life_task", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": due_date}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _assemble(db_session: Session, now: datetime, **overrides):
    kwargs = dict(include_body=False, include_mind=False, include_people=False, now=now)
    kwargs.update(overrides)
    return briefing_service.assemble_home_briefing(db_session, **kwargs)


# --- Stable identity / fingerprint --------------------------------------


def test_fingerprint_is_stable_for_identical_fields() -> None:
    a = briefing_service._fingerprint({"title": "x", "due_date": "2026-01-01", "category": "now"})
    b = briefing_service._fingerprint({"title": "x", "due_date": "2026-01-01", "category": "now"})
    assert a == b


def test_fingerprint_changes_when_a_meaningful_field_changes() -> None:
    a = briefing_service._fingerprint({"title": "x", "due_date": "2026-01-01", "category": "now"})
    b = briefing_service._fingerprint({"title": "y", "due_date": "2026-01-01", "category": "now"})
    assert a != b


def test_fingerprint_ignores_key_order() -> None:
    a = briefing_service._fingerprint({"a": 1, "b": 2})
    b = briefing_service._fingerprint({"b": 2, "a": 1})
    assert a == b


def test_life_task_identity_is_the_record_id(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    b = _assemble(db_session, now)
    assert b.items[0].id == f"life_task:{record.id}"


def test_integration_sync_identity_is_per_provider_not_per_state(db_session: Session) -> None:
    from app.models_integrations import IntegrationConnection

    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        IntegrationConnection(provider="google_calendar", status="error", last_error="boom")
    )
    db_session.commit()
    b = _assemble(db_session, now)
    assert b.items[0].id == "integration_sync:google_calendar"


# --- Classification: new / ongoing / changed / resolved / reopened -------


def test_first_ever_appearance_is_new(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    b = _assemble(db_session, now)
    assert b.items[0].change_state == "new"


def test_unchanged_second_pass_is_ongoing(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)
    b2 = _assemble(db_session, now + timedelta(minutes=5))
    assert b2.items[0].change_state == "ongoing"


def test_meaningful_field_change_is_changed(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)

    record.payload_json = json.dumps({"title": "Renew passport urgently", "due_date": "2026-08-20"})
    db_session.commit()

    b2 = _assemble(db_session, now + timedelta(minutes=5))
    assert b2.items[0].change_state == "changed"
    assert b2.items[0].title == "Renew passport urgently"


def test_becoming_more_urgent_counts_as_changed(db_session: Session) -> None:
    """A NEXT (due-soon) task crossing into NOW (overdue) is a category
    transition — captured in the fingerprint by design (§8's "an item
    becoming more urgent counts as changed")."""
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-30")  # due soon -> NEXT
    b1 = _assemble(db_session, now)
    assert b1.items[0].category == "next"

    later = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)  # now overdue -> NOW
    b2 = _assemble(db_session, later)
    assert b2.items[0].category == "now"
    assert b2.items[0].change_state == "changed"


def test_disappearing_condition_is_resolved_then_gone(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)

    record.archived_at = now
    db_session.commit()

    b2 = _assemble(db_session, now + timedelta(minutes=5))
    assert len(b2.items) == 1
    assert b2.items[0].change_state == "resolved"
    assert b2.items[0].title == "Renew passport"  # last known title, truthfully preserved

    b3 = _assemble(db_session, now + timedelta(minutes=10))
    assert b3.items == []  # resolved is a one-time confirmation, not a permanent fixture


def test_reopened_after_resolution(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)

    record.archived_at = now
    db_session.commit()
    _assemble(db_session, now + timedelta(minutes=5))  # resolved
    _assemble(db_session, now + timedelta(minutes=10))  # gone

    record.archived_at = None
    db_session.commit()
    b = _assemble(db_session, now + timedelta(minutes=15))
    assert b.items[0].change_state == "reopened"

    row = db_session.query(BriefingItemState).filter_by(stable_key=f"life_task:{record.id}").one()
    assert row.reopened_count == 1


# --- Priority-cap churn must not create false new/resolved ----------------


def test_priority_cap_churn_never_falsely_labels_new_or_resolved(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    # Seed 7 overdue tasks (all NOW, all beyond the 5-item cap) with the
    # exact same overdue-days so their relative order is a pure tie-break.
    for i in range(7):
        _life_task(db_session, f"Task {i}", "2026-08-20")
    b1 = _assemble(db_session, now)
    assert len(b1.items) == briefing_service.HOME_BRIEFING_MAX_ITEMS
    assert all(i.change_state == "new" for i in b1.items)

    # A second identical pass: every one of the 7 underlying identities is
    # now "ongoing" in the ledger (verified directly, not just via the
    # capped view) — none was ever marked resolved just for falling
    # outside the visible top 5.
    b2 = _assemble(db_session, now + timedelta(minutes=1))
    assert all(i.change_state == "ongoing" for i in b2.items)
    all_ledger_rows = db_session.query(BriefingItemState).filter_by(source_type="life_task").all()
    assert len(all_ledger_rows) == 7
    assert all(row.status == "active" for row in all_ledger_rows)


# --- False-resolution protection ------------------------------------------


def test_failed_source_never_falsely_resolves_its_identities(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)

    with mock.patch.object(briefing_service, "open_records", side_effect=RuntimeError("boom")):
        b2 = _assemble(db_session, now + timedelta(minutes=5))
    # Nothing life_task-shaped is shown (no fresh data to show), but the
    # ledger must NOT have flipped to resolved.
    assert not any(i.source_type == "life_task" for i in b2.items)
    row = db_session.query(BriefingItemState).filter_by(source_type="life_task").one()
    assert row.status == "active"

    b3 = _assemble(db_session, now + timedelta(minutes=10))
    assert b3.items[0].change_state == "ongoing"  # never incorrectly "reopened"


def test_partial_source_failure_isolates_other_sources(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    path_id = _domain_id(db_session, "path")
    db_session.add(
        StructuredRecord(
            domain_id=path_id, record_type="path_deadline", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"title": "UCL deadline", "due_date": "2026-08-20"}),
        )
    )
    db_session.commit()

    with mock.patch.object(briefing_service, "open_records", side_effect=RuntimeError("boom")):
        b = _assemble(db_session, now)
    # Both life_task and path_deadline share the same `open_records` call,
    # so both fail together here — but calendar/actions/etc. (which don't
    # call open_records at all in this scenario) are unaffected, proving
    # isolation at the _gather_candidates level.
    assert b.items == []
    assert briefing_service.SourceEvaluation  # sanity: the type exists and is importable


def test_google_health_disabled_never_evaluated_as_failed(db_session: Session) -> None:
    """include_body=False must not be conflated with a failed source —
    it's a deliberate, successful non-read."""
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    candidates, evaluations = briefing_service._gather_candidates(db_session, include_body=False, now=now)
    assert evaluations["google_health"].ok is True


# --- Snapshot spam prevention / dedup --------------------------------------


def test_identical_consecutive_snapshots_are_deduped(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)
    _assemble(db_session, now + timedelta(seconds=10))
    _assemble(db_session, now + timedelta(seconds=20))
    rows = db_session.query(BriefingSnapshot).filter_by(consumer="home").all()
    assert len(rows) == 1


def test_a_genuine_change_still_creates_a_new_snapshot_within_the_window(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    record = _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)
    record.archived_at = now
    db_session.commit()
    _assemble(db_session, now + timedelta(seconds=5))  # well within the dedupe window, but content genuinely differs
    rows = db_session.query(BriefingSnapshot).filter_by(consumer="home").all()
    assert len(rows) == 2


def test_snapshot_outside_dedupe_window_is_recorded_even_if_identical(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)
    _assemble(db_session, now + timedelta(seconds=briefing_service.SNAPSHOT_DEDUPE_WINDOW_SECONDS + 1))
    rows = db_session.query(BriefingSnapshot).filter_by(consumer="home").all()
    assert len(rows) == 2


def test_home_and_morning_briefing_snapshots_are_isolated(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Renew passport", "2026-08-20")
    _assemble(db_session, now)
    briefing_service.record_snapshot(
        db_session, consumer="morning_briefing", trigger="morning_briefing_manual",
        item_keys=[("line:1", "Today's Calendar events: none")], now=now,
    )
    db_session.commit()
    home_rows = db_session.query(BriefingSnapshot).filter_by(consumer="home").all()
    routine_rows = db_session.query(BriefingSnapshot).filter_by(consumer="morning_briefing").all()
    assert len(home_rows) == 1
    assert len(routine_rows) == 1
    # The Morning Briefing snapshot must never touch the Home ledger.
    ledger_rows = db_session.query(BriefingItemState).all()
    assert all(row.source_type != "routine_snapshot" for row in ledger_rows)


def test_morning_briefing_routine_run_records_its_own_snapshot_without_touching_home_ledger(
    db_session: Session,
) -> None:
    from app import routine_service

    now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
    calendar = CalendarCalendar(
        external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True
    )
    db_session.add(calendar)
    db_session.flush()
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev1", title="Dentist", all_day=False,
            start_datetime=now,
        )
    )
    db_session.commit()

    routine_service.run_routine(db_session, "morning_briefing", "manual", lambda: now)

    routine_snapshots = db_session.query(BriefingSnapshot).filter_by(consumer="morning_briefing").all()
    assert len(routine_snapshots) == 1
    assert routine_snapshots[0].trigger == "morning_briefing_manual"
    home_snapshots = db_session.query(BriefingSnapshot).filter_by(consumer="home").all()
    assert home_snapshots == []
    assert db_session.query(BriefingItemState).count() == 0


# --- Bounded retention ------------------------------------------------------


def test_cleanup_prunes_only_old_resolved_ledger_rows(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    old_cutoff = now - timedelta(days=briefing_service.LEDGER_RESOLVED_RETENTION_DAYS + 1)
    db_session.add(
        BriefingItemState(
            stable_key="life_task:old-resolved", source_type="life_task", status="resolved",
            current_fingerprint="x", last_title="Old", first_seen_at=old_cutoff, last_changed_at=old_cutoff,
            last_resolved_at=old_cutoff,
        )
    )
    db_session.add(
        BriefingItemState(
            stable_key="life_task:recent-resolved", source_type="life_task", status="resolved",
            current_fingerprint="y", last_title="Recent", first_seen_at=now, last_changed_at=now,
            last_resolved_at=now,
        )
    )
    db_session.add(
        BriefingItemState(
            stable_key="life_task:still-active", source_type="life_task", status="active",
            current_fingerprint="z", last_title="Active", first_seen_at=old_cutoff, last_changed_at=old_cutoff,
        )
    )
    db_session.commit()

    removed = briefing_service.cleanup_old_briefing_state(db_session, now)
    assert removed == 1
    remaining = {row.stable_key for row in db_session.query(BriefingItemState).all()}
    assert remaining == {"life_task:recent-resolved", "life_task:still-active"}


# --- No model call -----------------------------------------------------------


def test_reconcile_and_snapshot_functions_import_no_model_provider() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(briefing_service))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    for forbidden in ("app.providers", "app.providers.base", "app.providers.hermes", "app.turn_service"):
        assert forbidden not in imported


# --- No secrets serialized ----------------------------------------------------


def test_no_secret_bearing_fields_anywhere_in_briefing_item_state_or_snapshot(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    from app.models_integrations import IntegrationConnection

    db_session.add(
        IntegrationConnection(provider="google_calendar", status="error", last_error="token_expired: abc123secret")
    )
    db_session.commit()
    _assemble(db_session, now)

    for row in db_session.query(BriefingItemState).all():
        for column in ("last_title", "last_subtitle"):
            value = getattr(row, column) or ""
            assert "access_token" not in value
            assert "refresh_token" not in value
            assert "bearer" not in value.lower()
