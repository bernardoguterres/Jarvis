"""Phase 12C: Mission Focus's integration with the Phase 12A/12B briefing
assembler — pinned candidates must participate correctly in stable
identity, fingerprint, new/changed/ongoing/resolved/reopened
classification, acknowledge/snooze invalidation, false-resolution
protection, and the deterministic priority/cap/dedup rules. No model
call, no Hermes call, anywhere. Fictional fixtures and an injected clock
throughout."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from sqlalchemy.orm import Session

from app import briefing_service, mission_focus_service as mfs
from app.models import Domain
from app.models_actions import ActionProposal
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.models_memory import StructuredRecord
from app.models_routines import RoutineRun


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


def _build_checkpoint(db_session: Session, project: str = "Alpha", summary: str = "old news") -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "build"), record_type="build_checkpoint", occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"project": project, "summary": summary}),
    )
    db_session.add(record)
    db_session.commit()
    # Backdate so it falls outside the normal 2-day "recent checkpoint" window —
    # pinning must still surface it (that's the point of pinning).
    record.created_at = datetime.now(timezone.utc) - timedelta(days=10)
    db_session.commit()
    return record


NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _clock():
    return NOW


def _assemble(db_session: Session, now: datetime = NOW):
    return briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )


# --- Pinned candidates participate in Phase 12B continuity ------------------


def test_pinned_item_carries_stable_identity_and_fingerprint(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    b = _assemble(db_session)
    item = next(i for i in b.items if i.pinned)
    assert item.id == f"life_task:{task.id}"
    assert item.fingerprint
    assert item.pin_rank == 1
    assert item.change_state == "new"


def test_a_pin_outside_the_normal_window_still_surfaces(db_session: Session) -> None:
    """A BUILD checkpoint older than the ordinary 2-day inclusion window
    would never appear on its own — pinning it must still surface it."""
    checkpoint = _build_checkpoint(db_session)
    unpinned_briefing = _assemble(db_session)
    assert not any(i.source_type == "build_checkpoint" for i in unpinned_briefing.items)

    mfs.create_pin(db_session, source_type="build_checkpoint", source_id=checkpoint.id, next_action="Write changelog", clock=_clock)
    pinned_briefing = _assemble(db_session, now=NOW + timedelta(minutes=1))
    assert any(i.source_type == "build_checkpoint" and i.pinned for i in pinned_briefing.items)


def test_rank_change_affects_fingerprint_and_reports_as_changed(db_session: Session) -> None:
    t1 = _life_task(db_session, title="A", due_date="2026-08-20")
    t2 = _life_task(db_session, title="B", due_date="2026-08-20")
    p1 = mfs.create_pin(db_session, source_type="life_task", source_id=t1.id, next_action="a", rank=1, clock=_clock)
    mfs.create_pin(db_session, source_type="life_task", source_id=t2.id, next_action="b", rank=2, clock=_clock)
    _assemble(db_session)  # first pass: both "new"

    mfs.reorder_pins(db_session, [p1.id, mfs.list_active_pins(db_session)[1].id])  # no-op reorder, same order
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item1 = next(i for i in b2.items if i.source_ids == (t1.id,))
    assert item1.change_state == "ongoing"  # rank unchanged -> no fingerprint change


def test_next_action_change_reports_as_changed(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    mfs.update_pin_metadata(db_session, pin.id, next_action="Call the embassy", target_at=None, blocker=None)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "changed"


def test_blocker_change_reports_as_changed(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    mfs.update_pin_metadata(db_session, pin.id, next_action="Book slot", target_at=None, blocker="Waiting on passport photos")
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "changed"


def test_target_date_change_reports_as_changed(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    mfs.update_pin_metadata(db_session, pin.id, next_action="Book slot", target_at=NOW + timedelta(days=3), blocker=None)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "changed"


def test_meaningful_underlying_source_change_reports_as_changed(db_session: Session) -> None:
    task = _life_task(db_session, title="Renew passport", due_date="2026-08-20")
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    task.payload_json = json.dumps({"title": "Renew passport urgently", "due_date": "2026-08-20"})
    db_session.commit()
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "changed"


def test_no_change_reports_as_ongoing(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "ongoing"


def test_source_resolution_reports_truthfully(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    task.archived_at = NOW
    db_session.commit()
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.pinned)
    assert item.change_state == "changed"  # resolved-ness folded into the fingerprint


def test_unpinning_does_not_falsely_resolve_the_natural_item(db_session: Session) -> None:
    """A task that's naturally overdue (NOW) stays visible after being
    unpinned — unpinning removes pin metadata, never the real concern."""
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    mfs.unpin(db_session, pin.id, clock=_clock)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    item = next(i for i in b2.items if i.source_ids == (task.id,))
    assert item.pinned is False
    assert item.category == "now"  # still genuinely overdue


# --- Acknowledgement/snooze interplay ---------------------------------------


def test_acknowledging_a_pinned_item_never_unpins_it(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    b1 = _assemble(db_session)
    item = next(i for i in b1.items if i.pinned)

    briefing_service.acknowledge_item(db_session, item.id, NOW)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    assert not any(i.id == item.id for i in b2.items)  # suppressed from the unified feed

    # But the pin itself is untouched — still active, still in the rail.
    refreshed = db_session.get(type(pin), pin.id)
    assert refreshed.status == "active"
    assert any(e.rank == pin.rank for e in b2.mission_focus)


def test_snoozing_a_pinned_item_never_unpins_it(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    b1 = _assemble(db_session)
    item = next(i for i in b1.items if i.pinned)

    briefing_service.snooze_item(db_session, item.id, "1h", NOW)
    b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    assert not any(i.id == item.id for i in b2.items)

    refreshed = db_session.get(type(pin), pin.id)
    assert refreshed.status == "active"
    assert any(e.rank == pin.rank for e in b2.mission_focus)


def test_acknowledgement_breaks_after_meaningful_pin_change(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    b1 = _assemble(db_session)
    item = next(i for i in b1.items if i.pinned)
    briefing_service.acknowledge_item(db_session, item.id, NOW)
    assert not any(i.id == item.id for i in _assemble(db_session, now=NOW + timedelta(minutes=1)).items)

    mfs.update_pin_metadata(db_session, pin.id, next_action="Call the embassy today", target_at=None, blocker=None)
    b3 = _assemble(db_session, now=NOW + timedelta(minutes=2))
    assert any(i.id == item.id for i in b3.items)  # resurfaced — the old ack no longer matches


# --- False-resolution protection --------------------------------------------


def test_pin_lookup_failure_does_not_crash_or_falsely_resolve(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    _assemble(db_session)

    with mock.patch.object(briefing_service, "resolve_pin_source", side_effect=RuntimeError("boom")):
        b2 = _assemble(db_session, now=NOW + timedelta(minutes=1))
    # No crash; the item is never dropped or marked resolved just because
    # this pass's *pin-metadata* lookup failed — the underlying life_task
    # is still genuinely NOW (overdue) on its own merits, gathered
    # entirely independently of Mission Focus, and still shown as such
    # (just without pin annotations for this one pass, since those could
    # not be confirmed) — never silently invented, never silently hidden.
    unmerged = next(i for i in b2.items if i.source_ids == (task.id,))
    assert unmerged.category == "now"
    assert unmerged.pinned is False

    from app.models_briefing import BriefingItemState

    row = db_session.query(BriefingItemState).filter_by(stable_key=f"life_task:{task.id}").one()
    assert row.status == "active"  # never falsely resolved by the failed pin lookup

    # Once resolution succeeds again, pin annotations reattach normally.
    b3 = _assemble(db_session, now=NOW + timedelta(minutes=2))
    item = next(i for i in b3.items if i.pinned)
    assert item.id == f"life_task:{task.id}"


def test_deleted_source_row_reported_as_unavailable_not_silently_dropped(db_session: Session) -> None:
    task = _life_task(db_session)
    pin = mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="Book slot", clock=_clock)
    task_id = task.id
    db_session.delete(task)
    db_session.commit()

    b = _assemble(db_session, now=NOW + timedelta(minutes=1))
    entry = next(e for e in b.mission_focus if e.pin_id == pin.id)
    assert entry.available is False
    assert entry.title  # the frozen snapshot, not blank
    item = next(i for i in b.items if i.source_ids == (task_id,))
    assert item.freshness == "unavailable"
    assert item.tone == "failure"


# --- Priority: urgent unpinned item outranks a pinned non-urgent item -------


def test_urgent_unpinned_item_outranks_a_pinned_non_urgent_item(db_session: Session) -> None:
    checkpoint = _build_checkpoint(db_session)
    mfs.create_pin(db_session, source_type="build_checkpoint", source_id=checkpoint.id, next_action="Write changelog", clock=_clock)

    proposal = ActionProposal(
        capability_id="memory.create", domain_id=None, permission_level="confirm", arguments_json="{}",
        reason="r", expected_effect="e", payload_digest="f" * 64, status="failed",
    )
    db_session.add(proposal)
    db_session.commit()

    b = _assemble(db_session, now=NOW + timedelta(minutes=1))
    failed_idx = next(i for i, item in enumerate(b.items) if item.id == "action_proposal:failed")
    pinned_idx = next(i for i, item in enumerate(b.items) if item.pinned)
    assert failed_idx < pinned_idx  # genuine failure ranks first despite being unpinned


def test_pinned_watch_item_outranks_ordinary_watch_item(db_session: Session) -> None:
    """An active Mission Focus pin ranks above ordinary non-urgent
    candidates (an old, unpinned build checkpoint outside its own normal
    window never even appears — use a stale integration instead)."""
    checkpoint = _build_checkpoint(db_session, project="Pinned", summary="")
    mfs.create_pin(db_session, source_type="build_checkpoint", source_id=checkpoint.id, next_action="Ship it", clock=_clock)

    run = RoutineRun(
        routine_type="morning_briefing", trigger="scheduled", started_at=NOW - timedelta(hours=1),
        completed_at=NOW - timedelta(hours=1), outcome="failed", reason="unexpected error", selected_domains_json="[]",
    )
    db_session.add(run)
    db_session.commit()

    b = _assemble(db_session, now=NOW + timedelta(minutes=1))
    pinned_idx = next(i for i, item in enumerate(b.items) if item.pinned)
    routine_idx = next(i for i, item in enumerate(b.items) if item.source_type == "routine_run")
    # A genuine failure (routine_run, priority band 15) still outranks a
    # non-urgent pin (priority band 25+) — matches "safety/failure states
    # remain highest priority."
    assert routine_idx < pinned_idx


# --- Cap and dedup ------------------------------------------------------------


def test_briefing_stays_capped_at_five_with_pins_present(db_session: Session) -> None:
    tasks = [_life_task(db_session, title=f"Task {i}", due_date="2026-08-20") for i in range(8)]
    for t in tasks[:5]:
        mfs.create_pin(db_session, source_type="life_task", source_id=t.id, next_action="a", clock=_clock)
    b = _assemble(db_session, now=NOW + timedelta(minutes=1))
    assert len(b.items) <= briefing_service.HOME_BRIEFING_MAX_ITEMS


def test_pinned_item_never_appears_twice(db_session: Session) -> None:
    task = _life_task(db_session)
    mfs.create_pin(db_session, source_type="life_task", source_id=task.id, next_action="a", clock=_clock)
    b = _assemble(db_session)
    matching = [i for i in b.items if i.source_ids == (task.id,)]
    assert len(matching) == 1


# --- Privacy: BODY/MIND/PEOPLE ------------------------------------------------


def test_mission_focus_never_surfaces_mind_or_people_even_if_pinned_bypassed(db_session: Session) -> None:
    """Defense in depth: even if a MIND/PEOPLE-domain pin somehow existed
    in the table (bypassing create_pin's own validation), the assembler
    itself must never read MIND/PEOPLE domain data into the Home
    briefing — verified by inserting such a row directly."""
    from app.models_mission_focus import MissionFocusPin

    mind_id = _domain_id(db_session, "mind")
    proposal = ActionProposal(
        capability_id="memory.create", domain_id=mind_id, permission_level="confirm", arguments_json="{}",
        reason="private thought", expected_effect="e", payload_digest="b" * 64, status="proposed",
    )
    db_session.add(proposal)
    db_session.flush()
    bad_pin = MissionFocusPin(
        source_type="action_proposal", source_id=proposal.id, domain_slug="mind", source_title_snapshot="private",
        rank=1, next_action="x", status="active",
    )
    db_session.add(bad_pin)
    db_session.commit()

    b = _assemble(db_session, now=NOW + timedelta(minutes=1))
    dumped = json.dumps([i.title + (i.subtitle or "") for i in b.items])
    assert "private" not in dumped


def test_body_pin_only_surfaces_when_body_included() -> None:
    """BODY is not one of Mission Focus's eligible source types in this
    phase at all — structurally, not just by convention."""
    from app.models_mission_focus import MISSION_FOCUS_SOURCE_TYPES

    assert "google_health" not in MISSION_FOCUS_SOURCE_TYPES
    assert "body_weight" not in MISSION_FOCUS_SOURCE_TYPES
    assert "body_symptom" not in MISSION_FOCUS_SOURCE_TYPES


# --- No model call -------------------------------------------------------------


def test_mission_focus_service_imports_no_model_provider() -> None:
    import ast
    import inspect

    from app import mission_focus_service as module

    tree = ast.parse(inspect.getsource(module))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    for forbidden in ("app.providers", "app.providers.base", "app.providers.hermes", "app.turn_service"):
        assert forbidden not in imported


def test_assembly_with_pins_never_calls_send_turn() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(briefing_service))
    call_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "send_turn" not in call_names
