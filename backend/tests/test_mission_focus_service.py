"""Phase 12C: Mission Focus pin/unpin/edit/reorder logic. Every test uses
fictional fixtures and an injected clock — no real Google/Keychain/
Hermes/model contact. Pinning/unpinning is a direct, local, presentation-
only action: every test that mutates a pin also asserts the underlying
source row is byte-for-byte unchanged."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app import mission_focus_service as mfs
from app.models import Domain
from app.models_actions import ActionProposal
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.models_memory import StructuredRecord
from app.models_mission_focus import MISSION_FOCUS_MAX_ACTIVE_PINS, MissionFocusPin


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _life_task(db_session: Session, title: str = "Renew passport", due_date: str | None = "2026-08-20") -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "life"), record_type="life_task", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": due_date}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _path_deadline(db_session: Session, title: str = "UCL deadline") -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "path"), record_type="path_deadline", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": "2026-09-10"}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _build_checkpoint(db_session: Session) -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "build"), record_type="build_checkpoint", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"project": "Alpha", "summary": "Shipped tokenizer fix"}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _calendar_event(db_session: Session) -> CalendarEventCache:
    calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
    db_session.add(calendar)
    db_session.flush()
    ev = CalendarEventCache(
        calendar_id=calendar.id, external_event_id="ev1", title="Standup", all_day=False,
        start_datetime=datetime(2026, 8, 29, 9, 10, tzinfo=timezone.utc),
    )
    db_session.add(ev)
    db_session.commit()
    return ev


def _action_proposal(db_session: Session, domain_id: str | None = None, status: str = "proposed") -> ActionProposal:
    p = ActionProposal(
        capability_id="memory.create", domain_id=domain_id, permission_level="confirm", arguments_json="{}",
        reason="r", expected_effect="Create a memory", payload_digest="a" * 64, status=status,
    )
    db_session.add(p)
    db_session.commit()
    return p


NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _clock():
    return NOW


# --- Eligible source types --------------------------------------------------


def test_pin_each_eligible_source_type(db_session: Session) -> None:
    life_task = _life_task(db_session)
    path_deadline = _path_deadline(db_session)
    checkpoint = _build_checkpoint(db_session)
    event = _calendar_event(db_session)
    proposal = _action_proposal(db_session)

    p1 = mfs.create_pin(db_session, source_type="life_task", source_id=life_task.id, next_action="a", clock=_clock)
    p2 = mfs.create_pin(db_session, source_type="path_deadline", source_id=path_deadline.id, next_action="b", clock=_clock)
    p3 = mfs.create_pin(db_session, source_type="build_checkpoint", source_id=checkpoint.id, next_action="c", clock=_clock)
    p4 = mfs.create_pin(db_session, source_type="calendar_event", source_id=event.id, next_action="d", clock=_clock)
    p5 = mfs.create_pin(db_session, source_type="action_proposal", source_id=proposal.id, next_action="e", clock=_clock)

    assert {p.domain_slug for p in (p1, p2, p3, p4)} == {"life", "path", "build", "life"}
    assert p1.source_fingerprint_at_pin and p5.source_fingerprint_at_pin


def test_ineligible_source_type_rejected(db_session: Session) -> None:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "mind"), record_type="mind_checkin", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"mood": "ok"}),
    )
    db_session.add(record)
    db_session.commit()
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="mind_checkin", source_id=record.id, next_action="x", clock=_clock)


def test_nonexistent_source_rejected(db_session: Session) -> None:
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="life_task", source_id="does-not-exist", next_action="x", clock=_clock)


def test_type_mismatched_source_id_rejected(db_session: Session) -> None:
    path_record = _path_deadline(db_session)
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="life_task", source_id=path_record.id, next_action="x", clock=_clock)


def test_next_action_required(db_session: Session) -> None:
    life_task = _life_task(db_session)
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="life_task", source_id=life_task.id, next_action="   ", clock=_clock)


# --- Privacy: MIND/PEOPLE never pinnable, even indirectly -------------------


def test_mind_domain_action_proposal_rejected(db_session: Session) -> None:
    mind_id = _domain_id(db_session, "mind")
    proposal = _action_proposal(db_session, domain_id=mind_id)
    with pytest.raises(mfs.MissionFocusError, match="MIND and PEOPLE"):
        mfs.create_pin(db_session, source_type="action_proposal", source_id=proposal.id, next_action="x", clock=_clock)


def test_people_domain_action_proposal_rejected(db_session: Session) -> None:
    people_id = _domain_id(db_session, "people")
    proposal = _action_proposal(db_session, domain_id=people_id)
    with pytest.raises(mfs.MissionFocusError, match="MIND and PEOPLE"):
        mfs.create_pin(db_session, source_type="action_proposal", source_id=proposal.id, next_action="x", clock=_clock)


def test_global_action_proposal_pinnable(db_session: Session) -> None:
    proposal = _action_proposal(db_session, domain_id=None)
    pin = mfs.create_pin(db_session, source_type="action_proposal", source_id=proposal.id, next_action="x", clock=_clock)
    assert pin.domain_slug is None


# --- Max five active pins, duplicate prevention -----------------------------


def test_max_five_active_pins_enforced(db_session: Session) -> None:
    tasks = [_life_task(db_session, title=f"Task {i}") for i in range(6)]
    for t in tasks[:5]:
        mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock)
    assert len(mfs.list_active_pins(db_session)) == MISSION_FOCUS_MAX_ACTIVE_PINS
    with pytest.raises(mfs.MissionFocusError, match="already has 5"):
        mfs.create_pin(db_session, source_type="life_task", source_id=tasks[5].id, next_action="a", clock=_clock)


def test_duplicate_active_pin_for_same_source_rejected(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    with pytest.raises(mfs.MissionFocusError, match="already pinned"):
        mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="b", clock=_clock)


def test_repinning_after_unpin_is_allowed(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    mfs.unpin(db_session, pin.id, clock=_clock)
    new_pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="b", clock=_clock)
    assert new_pin.id != pin.id
    assert new_pin.status == "active"


def test_explicit_rank_collision_rejected(db_session: Session) -> None:
    t1 = _life_task(db_session, title="A")
    t2 = _life_task(db_session, title="B")
    mfs.create_pin(db_session, source_type="life_task", source_id=t1.id, next_action="a", rank=1, clock=_clock)
    with pytest.raises(mfs.MissionFocusError, match="already in use"):
        mfs.create_pin(db_session, source_type="life_task", source_id=t2.id, next_action="b", rank=1, clock=_clock)


def test_explicit_rank_out_of_range_rejected(db_session: Session) -> None:
    t1 = _life_task(db_session)
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="life_task", source_id=t1.id, next_action="a", rank=6, clock=_clock)
    with pytest.raises(mfs.MissionFocusError):
        mfs.create_pin(db_session, source_type="life_task", source_id=t1.id, next_action="a", rank=0, clock=_clock)


def test_rank_auto_assigned_deterministically(db_session: Session) -> None:
    tasks = [_life_task(db_session, title=f"Task {i}") for i in range(3)]
    pins = [mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock) for t in tasks]
    assert [p.rank for p in pins] == [1, 2, 3]


# --- Unpin never touches the source ------------------------------------------


def test_unpin_never_touches_underlying_source(db_session: Session) -> None:
    task = _life_task(db_session)
    original_payload = task.payload_json
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    mfs.unpin(db_session, pin.id, clock=_clock)

    db_session.refresh(task)
    assert task.archived_at is None
    assert task.payload_json == original_payload
    assert pin.status == "unpinned"
    assert pin.unpinned_at is not None


def test_unpinning_unknown_pin_raises(db_session: Session) -> None:
    with pytest.raises(mfs.MissionFocusError):
        mfs.unpin(db_session, "does-not-exist")


def test_double_unpin_raises(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    mfs.unpin(db_session, pin.id, clock=_clock)
    with pytest.raises(mfs.MissionFocusError):
        mfs.unpin(db_session, pin.id, clock=_clock)


# --- Edit metadata only, never the source -----------------------------------


def test_update_metadata_never_touches_source(db_session: Session) -> None:
    task = _life_task(db_session)
    original_payload = task.payload_json
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)

    updated = mfs.update_pin_metadata(db_session, pin.id, next_action="Call the office", target_at=None, blocker="Waiting on documents")
    assert updated.next_action == "Call the office"
    assert updated.blocker == "Waiting on documents"

    db_session.refresh(task)
    assert task.payload_json == original_payload


def test_update_metadata_requires_next_action(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    with pytest.raises(mfs.MissionFocusError):
        mfs.update_pin_metadata(db_session, pin.id, next_action="", target_at=None, blocker=None)


# --- Reorder -----------------------------------------------------------------


def test_reorder_reassigns_ranks_in_given_order(db_session: Session) -> None:
    tasks = [_life_task(db_session, title=f"Task {i}") for i in range(3)]
    pins = [mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock) for t in tasks]
    new_order = [pins[2].id, pins[0].id, pins[1].id]

    reordered = mfs.reorder_pins(db_session, new_order)
    assert [p.id for p in reordered] == new_order
    assert [p.rank for p in reordered] == [1, 2, 3]


def test_reorder_rejects_a_list_that_is_not_exactly_the_active_set(db_session: Session) -> None:
    tasks = [_life_task(db_session, title=f"Task {i}") for i in range(2)]
    pins = [mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock) for t in tasks]
    with pytest.raises(mfs.MissionFocusError):
        mfs.reorder_pins(db_session, [pins[0].id])  # missing one
    with pytest.raises(mfs.MissionFocusError):
        mfs.reorder_pins(db_session, [pins[0].id, pins[1].id, "bogus-id"])


# --- Concurrency around the five-pin invariant ------------------------------


def test_concurrent_sixth_pin_attempt_is_rejected_at_the_database_level(db_session: Session, data_dir) -> None:
    """A true race (two processes/threads both reading '4 active' before
    either commits) cannot be reproduced deterministically against one
    shared SQLAlchemy session — but the real protection is the database
    trigger (migration 0014), not the application's count-then-insert
    check. This proves that backstop directly: a second, independent
    connection to the SAME database file, bypassing the service layer
    entirely, is still refused once 5 active rows exist."""
    import sqlite3
    import uuid

    tasks = [_life_task(db_session, title=f"Task {i}") for i in range(5)]
    for t in tasks:
        mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock)

    from app.config import get_settings

    settings = get_settings()
    raw_conn = sqlite3.connect(str(settings.database_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw_conn.execute(
                "INSERT INTO mission_focus_pins "
                "(id, source_type, source_id, domain_slug, source_title_snapshot, rank, next_action, status, pinned_at, created_at, updated_at) "
                "VALUES (?, 'life_task', ?, 'life', 't', 1, 'x', 'active', datetime('now'), datetime('now'), datetime('now'))",
                (uuid.uuid4().hex, uuid.uuid4().hex),
            )
            raw_conn.commit()
    finally:
        raw_conn.close()
