"""Mission Control / Current Focus — lifecycle, timer, and candidate-reuse
logic. Every test uses fictional fixtures and an injected clock — no real
Google/Keychain/Hermes/model contact, exactly like the Mission Focus and
briefing test suites this mirrors."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app import mission_control_service as mcs
from app.briefing_service import BriefingItem, HomeBriefing
from app.models import Domain
from app.models_memory import StructuredRecord
from app.models_mission_control import FocusSession

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _life_task(db_session: Session, title: str = "Renew passport") -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "life"),
        record_type="life_task",
        occurred_at=NOW,
        payload_json=json.dumps({"title": title, "due_date": "2026-09-01"}),
    )
    db_session.add(record)
    db_session.commit()
    return record


def _item(
    item_id: str,
    category: str = "now",
    domain_slug: str | None = "life",
    source_type: str = "life_task",
    source_ids: tuple[str, ...] = ("x",),
) -> BriefingItem:
    return BriefingItem(
        id=item_id,
        category=category,  # type: ignore[arg-type]
        tone="neutral",  # type: ignore[arg-type]
        priority=1,
        title=f"Title {item_id}",
        subtitle=None,
        domain_slug=domain_slug,
        source_type=source_type,
        source_ids=source_ids,
        reason="because it's due soon",
        source_timestamp=NOW,
        freshness="fresh",  # type: ignore[arg-type]
        classification="ongoing",  # type: ignore[arg-type]
        link_target=None,
        fingerprint="fp-" + item_id,
    )


def _briefing(items: list[BriefingItem]) -> HomeBriefing:
    return HomeBriefing(
        generated_at=NOW,
        items=items,
        sources=[],
        include_body=False,
        include_mind=False,
        include_people=False,
    )


# --- Candidate assembly reuses the shared briefing assembler, never a second engine


def test_candidates_partition_now_next_and_watch_without_reassembly() -> None:
    items = [_item("a", "now"), _item("b", "next"), _item("c", "next"), _item("d", "watch")]
    result = mcs.mission_candidates(_briefing(items))
    assert result.recommended is not None and result.recommended.stable_key == "a"
    assert [c.stable_key for c in result.alternatives] == ["b", "c"]
    assert [c.stable_key for c in result.watch] == ["d"]
    assert result.generated_at == NOW


def test_candidates_cap_alternatives_at_two() -> None:
    items = [_item("a", "now"), _item("b", "next"), _item("c", "next"), _item("d", "next")]
    result = mcs.mission_candidates(_briefing(items))
    assert [c.stable_key for c in result.alternatives] == ["b", "c"]


def test_no_candidates_when_briefing_is_empty() -> None:
    result = mcs.mission_candidates(_briefing([]))
    assert result.recommended is None
    assert result.alternatives == []
    assert result.watch == []


# --- Starting a mission: source resolution, manual entry, validation


def test_start_mission_from_real_source_snapshots_title_and_domain(db_session: Session) -> None:
    task = _life_task(db_session, title="Renew passport")
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=45, now=NOW,
    )
    assert row.status == "active"
    assert row.started_at == NOW
    assert row.source_title_snapshot == "Renew passport"
    assert mcs.domain_slug_by_id(db_session, row.domain_id) == "life"


def test_start_manual_mission_requires_title(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title="   ", domain_slug="build", source_type="manual", source_id=None,
            target_duration_minutes=25, now=NOW,
        )


def test_start_manual_mission_with_domain(db_session: Session) -> None:
    row = mcs.start_mission(
        db_session, title="Write a memo", domain_slug="build", source_type="manual", source_id=None,
        target_duration_minutes=25, now=NOW,
    )
    assert row.title == "Write a memo"
    assert mcs.domain_slug_by_id(db_session, row.domain_id) == "build"
    assert row.source_id is None


def test_start_manual_mission_rejects_unknown_domain(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title="Write a memo", domain_slug="not-a-real-domain", source_type="manual", source_id=None,
            target_duration_minutes=25, now=NOW,
        )


def test_start_mission_rejects_malformed_source_reference(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id="does-not-exist",
            target_duration_minutes=25, now=NOW,
        )


def test_start_mission_rejects_missing_source_id_for_non_manual(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id=None,
            target_duration_minutes=25, now=NOW,
        )


def test_start_mission_rejects_unrecognized_source_type(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="mind_checkin", source_id="x",
            target_duration_minutes=25, now=NOW,
        )


@pytest.mark.parametrize("minutes", [0, 4, 181, 500])
def test_start_mission_rejects_out_of_range_duration(db_session: Session, minutes: int) -> None:
    task = _life_task(db_session)
    with pytest.raises(mcs.MissionControlError):
        mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
            target_duration_minutes=minutes, now=NOW,
        )


@pytest.mark.parametrize("minutes", [5, 25, 45, 60, 180])
def test_start_mission_accepts_boundary_durations(db_session: Session, minutes: int) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=minutes, now=NOW,
    )
    assert row.target_duration_minutes == minutes


# --- At most one active mission at a time


def test_only_one_active_or_paused_session_allowed(db_session: Session) -> None:
    task1 = _life_task(db_session, "Task A")
    task2 = _life_task(db_session, "Task B")
    mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task1.id,
        target_duration_minutes=25, now=NOW,
    )
    with pytest.raises(mcs.MissionControlError, match="already active or paused"):
        mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id=task2.id,
            target_duration_minutes=25, now=NOW,
        )


def test_starting_a_second_mission_allowed_after_first_completes(db_session: Session) -> None:
    task1 = _life_task(db_session, "Task A")
    task2 = _life_task(db_session, "Task B")
    first = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task1.id,
        target_duration_minutes=25, now=NOW,
    )
    mcs.complete_mission(db_session, first.id, NOW + timedelta(minutes=25))
    second = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task2.id,
        target_duration_minutes=25, now=NOW + timedelta(minutes=26),
    )
    assert second.status == "active"


def test_database_level_partial_unique_index_blocks_a_second_in_flight_row(db_session: Session, data_dir) -> None:
    """The real backstop is migration 0015's partial unique index, not just
    the service-layer count-then-insert check — proven directly against a
    second, independent raw connection to the same database file."""
    import sqlite3
    import uuid

    task = _life_task(db_session)
    mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )

    from app.config import get_settings

    settings = get_settings()
    raw_conn = sqlite3.connect(str(settings.database_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw_conn.execute(
                "INSERT INTO focus_sessions "
                "(id, title, source_type, status, target_duration_minutes, accumulated_paused_seconds, "
                "started_at, created_at, updated_at) "
                "VALUES (?, 'x', 'manual', 'active', 25, 0, datetime('now'), datetime('now'), datetime('now'))",
                (uuid.uuid4().hex,),
            )
            raw_conn.commit()
    finally:
        raw_conn.close()


# --- Timer correctness: elapsed/remaining derived from persisted state only


def test_elapsed_seconds_ticks_live_while_active(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=45, now=NOW,
    )
    later = NOW + timedelta(minutes=10)
    assert mcs.elapsed_seconds(row, later) == 600
    assert mcs.remaining_seconds(row, later) == 45 * 60 - 600


def test_pause_excludes_paused_time_from_elapsed(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=45, now=NOW,
    )
    paused_at = NOW + timedelta(minutes=10)
    row = mcs.pause_mission(db_session, row.id, paused_at)
    assert row.status == "paused"
    # Elapsed freezes at the moment of pausing, regardless of how much later "now" is queried.
    assert mcs.elapsed_seconds(row, paused_at + timedelta(minutes=30)) == 600

    resumed_at = paused_at + timedelta(minutes=5)  # paused for 5 minutes
    row = mcs.resume_mission(db_session, row.id, resumed_at)
    assert row.status == "active"
    assert row.accumulated_paused_seconds == 300

    later = resumed_at + timedelta(minutes=10)
    # 10 min before pause + 10 min after resume = 20 min of real focus time.
    assert mcs.elapsed_seconds(row, later) == 20 * 60


def test_completing_directly_from_paused_folds_the_final_pause_window(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=45, now=NOW,
    )
    paused_at = NOW + timedelta(minutes=10)
    row = mcs.pause_mission(db_session, row.id, paused_at)
    completed_at = paused_at + timedelta(minutes=15)  # 15 minutes paused, never resumed
    row = mcs.complete_mission(db_session, row.id, completed_at)
    assert row.status == "completed"
    assert row.accumulated_paused_seconds == 15 * 60
    # Only the 10 minutes before the pause count as focus time.
    assert mcs.elapsed_seconds(row, completed_at + timedelta(hours=1)) == 600


def test_abandoning_directly_from_paused_folds_the_final_pause_window(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=45, now=NOW,
    )
    paused_at = NOW + timedelta(minutes=5)
    row = mcs.pause_mission(db_session, row.id, paused_at)
    abandoned_at = paused_at + timedelta(minutes=2)
    row = mcs.abandon_mission(db_session, row.id, abandoned_at)
    assert row.status == "abandoned"
    assert mcs.elapsed_seconds(row, abandoned_at + timedelta(hours=1)) == 300


# --- Idempotency of duplicate lifecycle requests


def test_pause_is_idempotent(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    paused_at = NOW + timedelta(minutes=3)
    once = mcs.pause_mission(db_session, row.id, paused_at)
    twice = mcs.pause_mission(db_session, row.id, paused_at + timedelta(minutes=1))
    assert once.paused_at == twice.paused_at  # second call is a no-op, doesn't re-stamp paused_at


def test_resume_is_idempotent(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    again = mcs.resume_mission(db_session, row.id, NOW + timedelta(minutes=1))
    assert again.status == "active"
    assert again.accumulated_paused_seconds == 0


def test_complete_is_idempotent(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    completed_at = NOW + timedelta(minutes=25)
    once = mcs.complete_mission(db_session, row.id, completed_at, completion_note="done")
    twice = mcs.complete_mission(db_session, row.id, completed_at + timedelta(minutes=5), completion_note="done again")
    assert once.completed_at == twice.completed_at
    assert twice.completion_note == "done"  # unchanged by the duplicate call


def test_abandon_is_idempotent(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    abandoned_at = NOW + timedelta(minutes=3)
    once = mcs.abandon_mission(db_session, row.id, abandoned_at)
    twice = mcs.abandon_mission(db_session, row.id, abandoned_at + timedelta(minutes=1))
    assert once.completed_at == twice.completed_at


def test_cannot_pause_a_completed_session(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    row = mcs.complete_mission(db_session, row.id, NOW + timedelta(minutes=25))
    with pytest.raises(mcs.MissionControlError):
        mcs.pause_mission(db_session, row.id, NOW + timedelta(minutes=26))


def test_unknown_session_id_raises(db_session: Session) -> None:
    with pytest.raises(mcs.MissionControlError):
        mcs.pause_mission(db_session, "does-not-exist", NOW)


# --- Ending a mission never mutates the underlying source


def test_completing_a_mission_never_mutates_the_underlying_source(db_session: Session) -> None:
    task = _life_task(db_session, title="Renew passport")
    original_payload = task.payload_json
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    mcs.complete_mission(db_session, row.id, NOW + timedelta(minutes=25), completion_note="Filed the form")
    db_session.refresh(task)
    assert task.payload_json == original_payload
    assert task.archived_at is None


# --- History and retention


def test_history_returns_only_terminal_sessions_most_recent_first(db_session: Session) -> None:
    tasks = [_life_task(db_session, f"Task {i}") for i in range(3)]
    for i, task in enumerate(tasks):
        row = mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
            target_duration_minutes=25, now=NOW + timedelta(hours=i),
        )
        mcs.complete_mission(db_session, row.id, NOW + timedelta(hours=i, minutes=25))
    history = mcs.get_history(db_session, limit=10)
    assert [h.title for h in history] == ["Task 2", "Task 1", "Task 0"]


def test_cleanup_never_touches_active_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcs, "FOCUS_SESSION_HISTORY_RETENTION", 1)
    tasks = [_life_task(db_session, f"Task {i}") for i in range(3)]
    for i, task in enumerate(tasks[:2]):
        row = mcs.start_mission(
            db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
            target_duration_minutes=25, now=NOW + timedelta(hours=i),
        )
        mcs.complete_mission(db_session, row.id, NOW + timedelta(hours=i, minutes=25))
    active = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=tasks[2].id,
        target_duration_minutes=25, now=NOW + timedelta(hours=5),
    )
    removed = mcs.cleanup_old_focus_sessions(db_session)
    assert removed == 1  # only one of the two terminal rows kept beyond retention=1
    assert db_session.get(FocusSession, active.id) is not None
    assert db_session.get(FocusSession, active.id).status == "active"


# --- Timezone normalization (SQLite drops tzinfo on round-trip)


def test_started_at_and_paused_at_remain_timezone_aware_after_refresh(db_session: Session) -> None:
    task = _life_task(db_session)
    row = mcs.start_mission(
        db_session, title=None, domain_slug=None, source_type="life_task", source_id=task.id,
        target_duration_minutes=25, now=NOW,
    )
    assert row.started_at.tzinfo is not None
    fetched = mcs.get_current_session(db_session)
    assert fetched is not None
    assert fetched.started_at.tzinfo is not None

    paused = mcs.pause_mission(db_session, row.id, NOW + timedelta(minutes=1))
    assert paused.paused_at.tzinfo is not None
