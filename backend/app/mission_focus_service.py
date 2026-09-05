"""Phase 12C: Mission Focus — pin/unpin/edit/reorder logic.

Every mutation here is a direct, explicit user-interface action, never
the Phase 8 propose->approve->execute lifecycle: pinning/unpinning only
ever changes this module's own presentation/prioritization state, never
Calendar, memory, Health, or any other external source (CLAUDE.md §12).
No function here ever calls a model or Hermes, and none of them mutate
the underlying source row in any way — validated explicitly by tests that
assert the source is byte-for-byte unchanged after every operation here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.briefing_service import PinnedSourceInfo, _fingerprint, resolve_pin_source
from app.models_mission_focus import (
    MISSION_FOCUS_MAX_ACTIVE_PINS,
    MISSION_FOCUS_SOURCE_TYPES,
    MissionFocusPin,
)

# MIND/PEOPLE must remain structurally excluded from Home/Mission Focus,
# exactly like Phase 12A's Home briefing (app/briefing_service.py's module
# docstring) — enforced here, server-side, not merely by hiding a
# frontend control, since a pin's domain is always resolved and stored
# from the real source, never accepted from the client.
_FORBIDDEN_DOMAIN_SLUGS = ("mind", "people")


class MissionFocusError(Exception):
    pass


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def validate_and_resolve_for_pin(session: Session, source_type: str, source_id: str, now: datetime) -> PinnedSourceInfo:
    """Raises `MissionFocusError` for anything that isn't a genuinely
    eligible, existing, non-sensitive source. Never trusts the caller for
    domain — always resolved fresh from the real row."""
    if source_type not in MISSION_FOCUS_SOURCE_TYPES:
        raise MissionFocusError(f"source_type must be one of {MISSION_FOCUS_SOURCE_TYPES}, got {source_type!r}.")
    if not source_id:
        raise MissionFocusError("source_id is required.")
    info = resolve_pin_source(session, source_type, source_id, now)
    if info is None:
        raise MissionFocusError("That source could not be found.")
    if info.domain_slug in _FORBIDDEN_DOMAIN_SLUGS:
        raise MissionFocusError("MIND and PEOPLE content cannot be added to Mission Focus.")
    return info


def list_active_pins(session: Session) -> list[MissionFocusPin]:
    return session.query(MissionFocusPin).filter(MissionFocusPin.status == "active").order_by(MissionFocusPin.rank).all()


def _next_available_rank(session: Session) -> int:
    used = {row.rank for row in list_active_pins(session)}
    for candidate in range(1, MISSION_FOCUS_MAX_ACTIVE_PINS + 1):
        if candidate not in used:
            return candidate
    raise MissionFocusError(f"Mission Focus already has {MISSION_FOCUS_MAX_ACTIVE_PINS} active pins.")


def create_pin(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    next_action: str,
    target_at: datetime | None = None,
    blocker: str | None = None,
    rank: int | None = None,
    clock=_clock,
) -> MissionFocusPin:
    if not next_action or not next_action.strip():
        raise MissionFocusError("next_action is required — Bernardo's own written next step, never generated.")
    now = clock()
    info = validate_and_resolve_for_pin(session, source_type, source_id, now)

    existing = (
        session.query(MissionFocusPin)
        .filter(
            MissionFocusPin.source_type == source_type,
            MissionFocusPin.source_id == source_id,
            MissionFocusPin.status == "active",
        )
        .one_or_none()
    )
    if existing is not None:
        raise MissionFocusError("This item is already pinned to Mission Focus.")

    active_count = session.query(MissionFocusPin).filter(MissionFocusPin.status == "active").count()
    if active_count >= MISSION_FOCUS_MAX_ACTIVE_PINS:
        raise MissionFocusError(f"Mission Focus already has {MISSION_FOCUS_MAX_ACTIVE_PINS} active pins.")

    if rank is None:
        rank = _next_available_rank(session)
    elif not (1 <= rank <= MISSION_FOCUS_MAX_ACTIVE_PINS):
        raise MissionFocusError(f"rank must be between 1 and {MISSION_FOCUS_MAX_ACTIVE_PINS}.")
    elif session.query(MissionFocusPin).filter(MissionFocusPin.status == "active", MissionFocusPin.rank == rank).first():
        raise MissionFocusError(f"Rank {rank} is already in use by another active pin.")

    pin = MissionFocusPin(
        source_type=source_type,
        source_id=source_id,
        domain_slug=info.domain_slug,
        source_title_snapshot=info.title,
        rank=rank,
        next_action=next_action.strip(),
        target_at=target_at,
        blocker=blocker.strip() if blocker else None,
        source_fingerprint_at_pin=_fingerprint(info.natural_fields),
        status="active",
        pinned_at=now,
    )
    session.add(pin)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # The database-level trigger/partial-unique-index (migration 0014)
        # is the real backstop against a race that a plain application-
        # level count-then-insert check cannot fully close on its own.
        raise MissionFocusError(
            "Could not pin this item — Mission Focus may already be full, or it may already be pinned."
        ) from exc
    session.refresh(pin)
    return pin


def update_pin_metadata(
    session: Session,
    pin_id: str,
    *,
    next_action: str,
    target_at: datetime | None,
    blocker: str | None,
) -> MissionFocusPin:
    """Edits ONLY Mission Focus's own metadata — next_action/target_at/
    blocker. There is no code path here that writes to the underlying
    source row at all."""
    pin = session.get(MissionFocusPin, pin_id)
    if pin is None or pin.status != "active":
        raise MissionFocusError("Unknown or no longer active Mission Focus pin.")
    if not next_action or not next_action.strip():
        raise MissionFocusError("next_action is required.")
    pin.next_action = next_action.strip()
    pin.target_at = target_at
    pin.blocker = blocker.strip() if blocker else None
    session.commit()
    session.refresh(pin)
    return pin


def unpin(session: Session, pin_id: str, clock=_clock) -> MissionFocusPin:
    """Removes an item from Mission Focus. Never deletes the row (kept
    for history, mirroring Phase 12B's acknowledge/snooze retention
    pattern) and — critically — never touches the underlying source in
    any way: no archive, no completion, no deletion of the real
    StructuredRecord/CalendarEventCache/ActionProposal row."""
    pin = session.get(MissionFocusPin, pin_id)
    if pin is None or pin.status != "active":
        raise MissionFocusError("Unknown or no longer active Mission Focus pin.")
    pin.status = "unpinned"
    pin.unpinned_at = clock()
    session.commit()
    session.refresh(pin)
    return pin


def reorder_pins(session: Session, ordered_pin_ids: list[str]) -> list[MissionFocusPin]:
    """Reassigns rank 1..N (in the given order) to exactly the current
    set of active pins — `ordered_pin_ids` must name each active pin
    exactly once, nothing more, nothing less, so a stale/partial client
    payload can never silently drop a pin from view."""
    active = {pin.id: pin for pin in list_active_pins(session)}
    if set(ordered_pin_ids) != set(active):
        raise MissionFocusError("The reorder list must contain exactly the current active pins, no more and no fewer.")
    # Two-phase assignment (temporary, safely-out-of-the-way ranks first)
    # avoids transiently colliding with `uq_mission_focus_active_rank`
    # while permuting ranks among the very same active rows — SQLite has
    # no deferrable UNIQUE constraint to lean on instead. 1000+ is always
    # well clear of any real 1-5 rank; the model's CHECK constraint only
    # requires `>= 1`, so this remains valid at every intermediate step.
    for offset, pin_id in enumerate(ordered_pin_ids):
        active[pin_id].rank = 1000 + offset
    session.flush()
    for index, pin_id in enumerate(ordered_pin_ids, start=1):
        active[pin_id].rank = index
    session.commit()
    return list_active_pins(session)
