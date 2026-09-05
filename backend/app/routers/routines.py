"""Phase 10B: the fixed routine catalogue's HTTP surface. Configuring a
schedule or requesting a manual run is an explicit local UI action — it
never goes through the Phase 8 proposal lifecycle (no external side
effect of its own). "Discuss with Jarvis" is deliberately NOT a route
here: the frontend sends a completed routine's own text into a normal
conversation turn through the existing, already-model-using
`POST /api/conversations/{id}/turns` endpoint — the same context boundary
every other conversation goes through, never a routine-specific bypass.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import routine_service
from app.deps import get_db
from app.models_routines import ROUTINE_TYPES, RoutineRun
from app.schemas_routines import (
    RoutineCheckinResponseRequest,
    RoutineOutputSection,
    RoutineRunRead,
    RoutineScheduleRead,
    RoutineScheduleUpdateRequest,
)

router = APIRouter(tags=["routines"])


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _schedule_to_read(schedule) -> RoutineScheduleRead:
    try:
        selected = json.loads(schedule.selected_domains_json)
    except (json.JSONDecodeError, TypeError):
        selected = []
    return RoutineScheduleRead(
        routine_type=schedule.routine_type,
        enabled=schedule.enabled,
        local_time=schedule.local_time,
        weekday=schedule.weekday,
        timezone=schedule.timezone,
        selected_domains=selected,
        next_due_at=schedule.next_due_at,
        last_run_at=schedule.last_run_at,
        last_status=schedule.last_status,
        last_error=schedule.last_error,
        consecutive_failure_count=schedule.consecutive_failure_count,
    )


def _run_to_read(run: RoutineRun) -> RoutineRunRead:
    sections_data = json.loads(run.output_json).get("sections", []) if run.output_json else []
    try:
        selected = json.loads(run.selected_domains_json)
    except (json.JSONDecodeError, TypeError):
        selected = []
    try:
        responses = json.loads(run.responses_json) if run.responses_json else {}
    except (json.JSONDecodeError, TypeError):
        responses = {}
    return RoutineRunRead(
        id=run.id,
        routine_type=run.routine_type,
        trigger=run.trigger,
        started_at=run.started_at,
        completed_at=run.completed_at,
        outcome=run.outcome,
        reason=run.reason,
        sections=[RoutineOutputSection(**s) for s in sections_data],
        responses=responses,
        selected_domains=selected,
    )


@router.get("/api/routines/{routine_type}/schedule", response_model=RoutineScheduleRead)
def get_routine_schedule(routine_type: str, db: Session = Depends(get_db)) -> RoutineScheduleRead:
    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown routine type")
    schedule = routine_service.get_or_create_schedule(db, routine_type)
    db.commit()
    return _schedule_to_read(schedule)


@router.put("/api/routines/{routine_type}/schedule", response_model=RoutineScheduleRead)
def update_routine_schedule(
    routine_type: str, payload: RoutineScheduleUpdateRequest, db: Session = Depends(get_db)
) -> RoutineScheduleRead:
    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown routine type")
    try:
        schedule = routine_service.set_schedule(
            db,
            routine_type,
            enabled=payload.enabled,
            local_time=payload.local_time,
            timezone_name=payload.timezone,
            weekday=payload.weekday,
            selected_domains=payload.selected_domains,
            clock=_clock,
        )
    except routine_service.RoutineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _schedule_to_read(schedule)


@router.post("/api/routines/{routine_type}/run", response_model=RoutineRunRead)
def run_routine_now(routine_type: str, db: Session = Depends(get_db)) -> RoutineRunRead:
    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown routine type")
    run = routine_service.run_routine(db, routine_type, "manual", _clock)
    if run.outcome == "skipped":
        raise HTTPException(status_code=409, detail="A run of this routine is already in progress.")
    return _run_to_read(run)


@router.get("/api/routines/{routine_type}/history", response_model=list[RoutineRunRead])
def list_routine_history(routine_type: str, db: Session = Depends(get_db)) -> list[RoutineRunRead]:
    if routine_type not in ROUTINE_TYPES:
        raise HTTPException(status_code=404, detail="Unknown routine type")
    rows = (
        db.query(RoutineRun)
        .filter(RoutineRun.routine_type == routine_type)
        .order_by(RoutineRun.started_at.desc())
        .limit(20)
        .all()
    )
    return [_run_to_read(r) for r in rows]


@router.post("/api/routines/runs/{run_id}/responses", response_model=RoutineRunRead)
def record_checkin_responses(
    run_id: str, payload: RoutineCheckinResponseRequest, db: Session = Depends(get_db)
) -> RoutineRunRead:
    """Records Bernardo's own typed Evening Check-in answers on that run
    only — local, domain-scoped, never auto-promoted to a permanent
    memory (Phase 4's `memory_items`). A deliberate future "Remember this"
    on a specific answer is a separate, explicit action, not implied here."""
    run = db.get(RoutineRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Routine run not found")
    run.responses_json = json.dumps(payload.responses)
    db.commit()
    db.refresh(run)
    return _run_to_read(run)
