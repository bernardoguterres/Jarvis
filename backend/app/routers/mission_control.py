"""Mission Control / Current Focus's HTTP surface. Every mutation here is
a direct, explicit local action (CLAUDE.md §12 "Read"-tier presentation/
timer state) — never the Phase 8 propose->approve->execute lifecycle,
since nothing here ever touches Calendar, memory, Health, or any other
external source, and ending a session never mutates the source it was
started from. There is no "Discuss with Jarvis" route here either,
matching the Phase 10B/12A/12C pattern: the frontend sends the current
mission/history into a normal conversation turn through the existing,
already-model-using general-conversation endpoints — only when Bernardo
explicitly asks for that.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import briefing_service, mission_control_service
from app.deps import get_db
from app.models_mission_control import FocusSession
from app.schemas_mission_control import (
    AbandonMissionRequest,
    CompleteMissionRequest,
    CurrentMissionRead,
    FocusSessionRead,
    MissionCandidateRead,
    MissionCandidatesRead,
    PauseMissionRequest,
    ResumeMissionRequest,
    StartMissionRequest,
)

router = APIRouter(tags=["mission-control"])


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _session_to_read(db: Session, row: FocusSession, now: datetime) -> FocusSessionRead:
    return FocusSessionRead(
        id=row.id,
        title=row.title,
        domain_slug=mission_control_service.domain_slug_by_id(db, row.domain_id),
        source_type=row.source_type,
        source_id=row.source_id,
        source_title_snapshot=row.source_title_snapshot,
        status=row.status,
        target_duration_minutes=row.target_duration_minutes,
        started_at=row.started_at,
        paused_at=row.paused_at,
        accumulated_paused_seconds=row.accumulated_paused_seconds,
        completed_at=row.completed_at,
        completion_note=row.completion_note,
        what_changed_note=row.what_changed_note,
        abandoned_reason=row.abandoned_reason,
        elapsed_seconds=mission_control_service.elapsed_seconds(row, now),
        remaining_seconds=mission_control_service.remaining_seconds(row, now),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/api/mission-control/candidates", response_model=MissionCandidatesRead)
def get_mission_candidates(db: Session = Depends(get_db)) -> MissionCandidatesRead:
    """Reuses the exact same NOW/NEXT/WATCH assembler Home's own briefing
    uses (`app.briefing_service.assemble_home_briefing`) — never a second
    prioritization engine. Uses the existing `trigger="home_view"` value
    (migration 0013's fixed, already-at-head `BRIEFING_SNAPSHOT_TRIGGERS`
    enum has no dedicated Mission Control entry, and CLAUDE.md forbids
    editing a migration already at head) — this call shares the exact
    same underlying ledger/snapshot trail as Home's own view, so it can
    never disagree with what Home itself would show."""
    now = _clock()
    settings = briefing_service.get_or_create_settings(db)
    briefing = briefing_service.assemble_home_briefing(
        db,
        include_body=settings.include_body,
        include_mind=settings.include_mind,
        include_people=settings.include_people,
        now=now,
        trigger="home_view",
    )
    candidates = mission_control_service.mission_candidates(briefing)
    return MissionCandidatesRead(
        recommended=MissionCandidateRead(**vars(candidates.recommended)) if candidates.recommended else None,
        alternatives=[MissionCandidateRead(**vars(c)) for c in candidates.alternatives],
        watch=[MissionCandidateRead(**vars(c)) for c in candidates.watch],
        generated_at=candidates.generated_at,
    )


@router.get("/api/mission-control/current", response_model=CurrentMissionRead)
def get_current_mission(db: Session = Depends(get_db)) -> CurrentMissionRead:
    now = _clock()
    row = mission_control_service.get_current_session(db)
    return CurrentMissionRead(session=_session_to_read(db, row, now) if row else None)


@router.get("/api/mission-control/history", response_model=list[FocusSessionRead])
def get_mission_history(limit: int = 20, db: Session = Depends(get_db)) -> list[FocusSessionRead]:
    now = _clock()
    limit = max(1, min(100, limit))
    rows = mission_control_service.get_history(db, limit=limit)
    return [_session_to_read(db, row, now) for row in rows]


@router.post("/api/mission-control/sessions", response_model=FocusSessionRead, status_code=201)
def start_mission(payload: StartMissionRequest, db: Session = Depends(get_db)) -> FocusSessionRead:
    try:
        row = mission_control_service.start_mission(
            db,
            title=payload.title,
            domain_slug=payload.domain_slug,
            source_type=payload.source_type,
            source_id=payload.source_id,
            target_duration_minutes=payload.target_duration_minutes,
            now=_clock(),
        )
    except mission_control_service.MissionControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_to_read(db, row, _clock())


@router.post("/api/mission-control/sessions/{session_id}/pause", response_model=FocusSessionRead)
def pause_mission(session_id: str, _payload: PauseMissionRequest, db: Session = Depends(get_db)) -> FocusSessionRead:
    try:
        row = mission_control_service.pause_mission(db, session_id, _clock())
    except mission_control_service.MissionControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_to_read(db, row, _clock())


@router.post("/api/mission-control/sessions/{session_id}/resume", response_model=FocusSessionRead)
def resume_mission(session_id: str, _payload: ResumeMissionRequest, db: Session = Depends(get_db)) -> FocusSessionRead:
    try:
        row = mission_control_service.resume_mission(db, session_id, _clock())
    except mission_control_service.MissionControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_to_read(db, row, _clock())


@router.post("/api/mission-control/sessions/{session_id}/complete", response_model=FocusSessionRead)
def complete_mission(session_id: str, payload: CompleteMissionRequest, db: Session = Depends(get_db)) -> FocusSessionRead:
    try:
        row = mission_control_service.complete_mission(
            db, session_id, _clock(), completion_note=payload.completion_note, what_changed_note=payload.what_changed_note
        )
    except mission_control_service.MissionControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_to_read(db, row, _clock())


@router.post("/api/mission-control/sessions/{session_id}/abandon", response_model=FocusSessionRead)
def abandon_mission(session_id: str, payload: AbandonMissionRequest, db: Session = Depends(get_db)) -> FocusSessionRead:
    try:
        row = mission_control_service.abandon_mission(db, session_id, _clock(), completion_note=payload.completion_note)
    except mission_control_service.MissionControlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_to_read(db, row, _clock())
