"""Phase 12C: Mission Focus's HTTP surface. Every mutation here is a
direct, explicit user-interface action (CLAUDE.md §12 "Read"-tier
presentation state) — never the Phase 8 propose->approve->execute
lifecycle, since nothing here ever touches Calendar, memory, Health, or
any other external source. There is no "Discuss Mission Focus with
Jarvis" route here either, matching the existing Phase 10B/12A pattern:
the frontend sends the current pins into a normal conversation turn
through the existing, already-model-using general-conversation endpoints.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import mission_focus_service
from app.briefing_service import resolve_pin_source
from app.deps import get_db
from app.models_mission_focus import MISSION_FOCUS_DEFAULT_VISIBLE, MISSION_FOCUS_MAX_ACTIVE_PINS, MissionFocusPin
from app.schemas_mission_focus import (
    MissionFocusPinCreateRequest,
    MissionFocusPinRead,
    MissionFocusPinUpdateRequest,
    MissionFocusReorderRequest,
    MissionFocusStateRead,
)

router = APIRouter(tags=["mission-focus"])


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _pin_to_read(session: Session, pin: MissionFocusPin, now: datetime) -> MissionFocusPinRead:
    try:
        info = resolve_pin_source(session, pin.source_type, pin.source_id, now)
    except Exception:
        info = None
    if info is None:
        title = pin.source_title_snapshot or f"({pin.source_type})"
        subtitle = None
        link_target = None
        available = False
        resolved = False
    else:
        title = info.title
        subtitle = info.subtitle
        link_target = info.link_target
        available = True
        resolved = info.resolved
    return MissionFocusPinRead(
        id=pin.id,
        source_type=pin.source_type,
        source_id=pin.source_id,
        domain_slug=pin.domain_slug,
        rank=pin.rank,
        next_action=pin.next_action,
        target_at=pin.target_at,
        blocker=pin.blocker,
        status=pin.status,
        pinned_at=pin.pinned_at,
        unpinned_at=pin.unpinned_at,
        title=title,
        subtitle=subtitle,
        link_target=link_target,
        available=available,
        resolved=resolved,
        change_state=None,  # only meaningful via GET /api/briefing/home's own reconciliation pass
    )


@router.get("/api/mission-focus", response_model=MissionFocusStateRead)
def get_mission_focus(db: Session = Depends(get_db)) -> MissionFocusStateRead:
    now = _clock()
    pins = mission_focus_service.list_active_pins(db)
    return MissionFocusStateRead(
        active_pins=[_pin_to_read(db, pin, now) for pin in pins],
        max_active_pins=MISSION_FOCUS_MAX_ACTIVE_PINS,
        default_visible=MISSION_FOCUS_DEFAULT_VISIBLE,
    )


@router.post("/api/mission-focus/pins", response_model=MissionFocusPinRead, status_code=201)
def create_mission_focus_pin(payload: MissionFocusPinCreateRequest, db: Session = Depends(get_db)) -> MissionFocusPinRead:
    try:
        pin = mission_focus_service.create_pin(
            db,
            source_type=payload.source_type,
            source_id=payload.source_id,
            next_action=payload.next_action,
            target_at=payload.target_at,
            blocker=payload.blocker,
            rank=payload.rank,
        )
    except mission_focus_service.MissionFocusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _pin_to_read(db, pin, _clock())


@router.put("/api/mission-focus/pins/{pin_id}", response_model=MissionFocusPinRead)
def update_mission_focus_pin(
    pin_id: str, payload: MissionFocusPinUpdateRequest, db: Session = Depends(get_db)
) -> MissionFocusPinRead:
    try:
        pin = mission_focus_service.update_pin_metadata(
            db, pin_id, next_action=payload.next_action, target_at=payload.target_at, blocker=payload.blocker
        )
    except mission_focus_service.MissionFocusError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _pin_to_read(db, pin, _clock())


@router.post("/api/mission-focus/pins/{pin_id}/unpin", response_model=MissionFocusPinRead)
def unpin_mission_focus_pin(pin_id: str, db: Session = Depends(get_db)) -> MissionFocusPinRead:
    try:
        pin = mission_focus_service.unpin(db, pin_id)
    except mission_focus_service.MissionFocusError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _pin_to_read(db, pin, _clock())


@router.put("/api/mission-focus/reorder", response_model=MissionFocusStateRead)
def reorder_mission_focus(payload: MissionFocusReorderRequest, db: Session = Depends(get_db)) -> MissionFocusStateRead:
    try:
        pins = mission_focus_service.reorder_pins(db, payload.pin_ids)
    except mission_focus_service.MissionFocusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = _clock()
    return MissionFocusStateRead(
        active_pins=[_pin_to_read(db, pin, now) for pin in pins],
        max_active_pins=MISSION_FOCUS_MAX_ACTIVE_PINS,
        default_visible=MISSION_FOCUS_DEFAULT_VISIBLE,
    )
