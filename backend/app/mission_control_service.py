"""Mission Control: one persistent, timed focus session at a time, with
candidates taken from the Home briefing.

No model or Hermes call. Candidates come from an already-assembled
`HomeBriefing`, so there is no second ranking engine, and source
references resolve through `briefing_service.resolve_pin_source()`.
Ending a session never changes the item it came from. Only one session
can be active or paused, enforced here and by a partial unique index
(migration 0015). Elapsed time is always computed from stored
timestamps, so a restart stays accurate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.briefing_service import (
    BriefingItem,
    HomeBriefing,
    PinnedSourceInfo,
    domain_id_by_slug,
    resolve_pin_source,
)
from app.models import Domain
from app.models_mission_control import (
    FOCUS_SESSION_MAX_MINUTES,
    FOCUS_SESSION_MIN_MINUTES,
    FOCUS_SESSION_SOURCE_TYPES,
    FocusSession,
)
from app.recall_index_service import sync_recall

# Real, already-existing source types a mission may reference: the same
# five Mission Focus already validates, plus 'manual' for free text.
_RESOLVABLE_SOURCE_TYPES = ("life_task", "path_deadline", "build_checkpoint", "calendar_event", "action_proposal")

FOCUS_DURATION_PRESETS_MINUTES = (25, 45, 60)

# History retention. Mirrors routine_service's ROUTINE_RUN_RETENTION_PER_TYPE
# and briefing_service's SNAPSHOT_RETENTION_PER_CONSUMER pattern: a bounded
# count of terminal (completed/abandoned) rows, never the current
# active/paused session.
FOCUS_SESSION_HISTORY_RETENTION = 200


class MissionControlError(Exception):
    pass


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip even through a `DateTime(timezone=
    True)` column, so normalize back to aware
    UTC at every read boundary rather than trusting a value fetched fresh
    from the database to still be aware."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def elapsed_seconds(row: FocusSession, now: datetime) -> int:
    """Derives elapsed *focus* time (paused time excluded) purely from
    persisted timestamps, never a decrementing frontend interval. Frozen
    at `completed_at` for a terminal session, at `paused_at` while
    currently paused, or ticking live against `now` while active."""
    started_at = _as_aware(row.started_at)
    if started_at is None:
        return 0
    if row.status in ("completed", "abandoned"):
        end = _as_aware(row.completed_at) or started_at
    elif row.status == "paused":
        end = _as_aware(row.paused_at) or started_at
    else:
        end = now
    total = (end - started_at).total_seconds() - row.accumulated_paused_seconds
    return max(0, int(total))


def remaining_seconds(row: FocusSession, now: datetime) -> int:
    target = row.target_duration_minutes * 60
    return max(0, target - elapsed_seconds(row, now))


@dataclass(frozen=True)
class MissionCandidate:
    """One candidate the briefing assembler already surfaced, reshaped for
    "what should I do now" rather than a triage list. The same
    `BriefingItem` fields, never independently re-derived."""

    stable_key: str
    domain_slug: str | None
    title: str
    subtitle: str | None
    reason: str
    source_type: str
    source_ids: tuple[str, ...]
    freshness: str
    link_target: str | None


def _to_candidate(item: BriefingItem) -> MissionCandidate:
    return MissionCandidate(
        stable_key=item.id,
        domain_slug=item.domain_slug,
        title=item.title,
        subtitle=item.subtitle,
        reason=item.reason,
        source_type=item.source_type,
        source_ids=item.source_ids,
        freshness=item.freshness,
        link_target=item.link_target,
    )


@dataclass(frozen=True)
class MissionControlCandidates:
    """At most one recommended candidate, at most two alternatives (both
    drawn from the briefing's NOW/NEXT items, already deterministically
    sorted), and any WATCH items shown separately. Never a claim that this
    represents Bernardo's actual preference; it is always presented as
    "suggested from current information."""

    recommended: MissionCandidate | None
    alternatives: list[MissionCandidate]
    watch: list[MissionCandidate]
    generated_at: datetime


def mission_candidates(briefing: HomeBriefing) -> MissionControlCandidates:
    """Partitions an already-assembled `HomeBriefing` (from
    `assemble_home_briefing()`, never re-computed here) into a Mission
    Control candidate view. Deliberately takes the already-built
    `HomeBriefing` rather than a session/now pair, so a caller that
    already fetched the Home briefing this turn (or a test with a fixed
    fixture) never triggers a second assembly pass, ledger write, or
    snapshot record."""
    now_next = [item for item in briefing.items if item.category in ("now", "next")]
    watch = [item for item in briefing.items if item.category == "watch"]
    recommended = _to_candidate(now_next[0]) if now_next else None
    alternatives = [_to_candidate(item) for item in now_next[1:3]]
    return MissionControlCandidates(
        recommended=recommended,
        alternatives=alternatives,
        watch=[_to_candidate(item) for item in watch],
        generated_at=briefing.generated_at,
    )


def domain_slug_by_id(session: Session, domain_id: str | None) -> str | None:
    if domain_id is None:
        return None
    domain = session.get(Domain, domain_id)
    return domain.slug if domain else None


def get_current_session(session: Session) -> FocusSession | None:
    row = session.execute(select(FocusSession).where(FocusSession.status.in_(("active", "paused")))).scalar_one_or_none()
    if row is not None:
        row.started_at = _as_aware(row.started_at)
        row.paused_at = _as_aware(row.paused_at)
    return row


def _validate_duration(minutes: int) -> None:
    if not (FOCUS_SESSION_MIN_MINUTES <= minutes <= FOCUS_SESSION_MAX_MINUTES):
        raise MissionControlError(
            f"target_duration_minutes must be between {FOCUS_SESSION_MIN_MINUTES} and {FOCUS_SESSION_MAX_MINUTES}."
        )


def start_mission(
    session: Session,
    *,
    title: str | None,
    domain_slug: str | None,
    source_type: str,
    source_id: str | None,
    target_duration_minutes: int,
    now: datetime,
) -> FocusSession:
    """Creates a focus session and immediately starts it (`status='active'`,
    `started_at=now`). This is the one atomic action behind "Start", "Focus on
    this for 45 minutes", and every other entry point. Raises
    `MissionControlError` (never a bare exception, never a silent guess)
    for: a session already in flight, an out-of-range duration, an
    unresolvable source reference, or a manual mission naming an
    unrecognized domain."""
    if get_current_session(session) is not None:
        raise MissionControlError("A focus session is already active or paused. Complete or abandon it first.")
    _validate_duration(target_duration_minutes)

    if source_type not in FOCUS_SESSION_SOURCE_TYPES:
        raise MissionControlError(f"Unrecognized source_type: {source_type!r}.")

    resolved_domain_slug = domain_slug
    source_title_snapshot: str | None = None
    resolved_title = title

    if source_type == "manual":
        if not title or not title.strip():
            raise MissionControlError("A manually entered mission requires a title.")
        if domain_slug is not None:
            domain_id = domain_id_by_slug(session, domain_slug)
            if domain_id is None:
                raise MissionControlError(f"Unrecognized domain: {domain_slug!r}.")
        resolved_title = title.strip()
    else:
        if not source_id:
            raise MissionControlError(f"source_id is required for source_type {source_type!r}.")
        info: PinnedSourceInfo | None = resolve_pin_source(session, source_type, source_id, now)
        if info is None:
            raise MissionControlError("That source item could not be found.")
        resolved_domain_slug = info.domain_slug
        source_title_snapshot = info.title
        resolved_title = title.strip() if title and title.strip() else info.title

    domain_id = domain_id_by_slug(session, resolved_domain_slug) if resolved_domain_slug else None

    row = FocusSession(
        title=resolved_title,
        domain_id=domain_id,
        source_type=source_type,
        source_id=source_id if source_type != "manual" else None,
        source_title_snapshot=source_title_snapshot,
        status="active",
        target_duration_minutes=target_duration_minutes,
        started_at=now,
        accumulated_paused_seconds=0,
    )
    session.add(row)
    session.flush()
    sync_recall(session, "mission_control_session", row.id)
    session.commit()
    session.refresh(row)
    row.started_at = _as_aware(row.started_at)
    return row


def _require_current(session: Session, session_id: str) -> FocusSession:
    row = session.get(FocusSession, session_id)
    if row is None:
        raise MissionControlError("No such focus session.")
    return row


def pause_mission(session: Session, session_id: str, now: datetime) -> FocusSession:
    row = _require_current(session, session_id)
    if row.status == "paused":
        return row  # idempotent: a duplicate/retried request is a safe no-op
    if row.status != "active":
        raise MissionControlError(f"Cannot pause a session in status {row.status!r}.")
    row.paused_at = now
    row.status = "paused"
    session.commit()
    session.refresh(row)
    row.started_at = _as_aware(row.started_at)
    row.paused_at = _as_aware(row.paused_at)
    return row


def resume_mission(session: Session, session_id: str, now: datetime) -> FocusSession:
    row = _require_current(session, session_id)
    if row.status == "active":
        return row  # idempotent
    if row.status != "paused":
        raise MissionControlError(f"Cannot resume a session in status {row.status!r}.")
    paused_at = _as_aware(row.paused_at)
    assert paused_at is not None
    row.accumulated_paused_seconds += max(0, int((now - paused_at).total_seconds()))
    row.paused_at = None
    row.status = "active"
    session.commit()
    session.refresh(row)
    row.started_at = _as_aware(row.started_at)
    return row


def _fold_pause_if_any(row: FocusSession, now: datetime) -> None:
    """Ending (complete/abandon) directly from `paused` must not silently
    count the final paused window as focus time, so fold it in first,
    exactly like a resume immediately followed by an end."""
    if row.status == "paused" and row.paused_at is not None:
        paused_at = _as_aware(row.paused_at)
        assert paused_at is not None
        row.accumulated_paused_seconds += max(0, int((now - paused_at).total_seconds()))
        row.paused_at = None


def complete_mission(
    session: Session,
    session_id: str,
    now: datetime,
    *,
    completion_note: str | None = None,
    what_changed_note: str | None = None,
) -> FocusSession:
    row = _require_current(session, session_id)
    if row.status == "completed":
        return row  # idempotent
    if row.status not in ("active", "paused"):
        raise MissionControlError(f"Cannot complete a session in status {row.status!r}.")
    _fold_pause_if_any(row, now)
    row.status = "completed"
    row.completed_at = now
    if completion_note is not None:
        row.completion_note = completion_note
    if what_changed_note is not None:
        row.what_changed_note = what_changed_note
    session.flush()
    sync_recall(session, "mission_control_session", row.id)
    session.commit()
    session.refresh(row)
    row.started_at = _as_aware(row.started_at)
    row.completed_at = _as_aware(row.completed_at)
    return row


def abandon_mission(
    session: Session,
    session_id: str,
    now: datetime,
    *,
    completion_note: str | None = None,
) -> FocusSession:
    row = _require_current(session, session_id)
    if row.status == "abandoned":
        return row  # idempotent
    if row.status not in ("active", "paused", "planned"):
        raise MissionControlError(f"Cannot abandon a session in status {row.status!r}.")
    _fold_pause_if_any(row, now)
    row.status = "abandoned"
    row.completed_at = now
    if completion_note is not None:
        row.completion_note = completion_note
    session.flush()
    sync_recall(session, "mission_control_session", row.id)
    session.commit()
    session.refresh(row)
    row.started_at = _as_aware(row.started_at)
    row.completed_at = _as_aware(row.completed_at)
    return row


def get_history(session: Session, limit: int = 20) -> list[FocusSession]:
    rows = (
        session.execute(
            select(FocusSession)
            .where(FocusSession.status.in_(("completed", "abandoned")))
            .order_by(FocusSession.completed_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.started_at = _as_aware(row.started_at)
        row.completed_at = _as_aware(row.completed_at)
    return list(rows)


def cleanup_old_focus_sessions(session: Session) -> int:
    """Bounded history retention. Mirrors routine_service's/briefing_
    service's own established pattern: keep the most recent
    `FOCUS_SESSION_HISTORY_RETENTION` terminal rows, prune the rest. The
    current active/paused session (if any) is never a candidate for
    pruning, since this only ever selects `completed`/`abandoned` rows."""
    ids = [
        row[0]
        for row in session.execute(
            select(FocusSession.id)
            .where(FocusSession.status.in_(("completed", "abandoned")))
            .order_by(FocusSession.completed_at.desc())
        ).all()
    ]
    stale_ids = ids[FOCUS_SESSION_HISTORY_RETENTION:]
    if not stale_ids:
        return 0
    session.query(FocusSession).filter(FocusSession.id.in_(stale_ids)).delete(synchronize_session=False)
    session.commit()
    return len(stale_ids)
