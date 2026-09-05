"""Phase 10B: request/response models for the fixed routine catalogue.
Never includes a credential — routine configuration/output has none."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RoutineScheduleRead(BaseModel):
    routine_type: str
    enabled: bool
    local_time: str
    weekday: int | None
    timezone: str
    selected_domains: list[str]
    next_due_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    consecutive_failure_count: int


class RoutineScheduleUpdateRequest(BaseModel):
    enabled: bool
    local_time: str = "08:00"
    timezone: str = "UTC"
    weekday: int | None = None
    selected_domains: list[str] = []


class RoutineOutputLine(BaseModel):
    text: str
    source_ref: str | None


class RoutineOutputSection(BaseModel):
    title: str
    lines: list[RoutineOutputLine]


class RoutineRunRead(BaseModel):
    id: str
    routine_type: str
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    outcome: str
    reason: str | None
    sections: list[RoutineOutputSection]
    responses: dict[str, str]
    selected_domains: list[str]


class RoutineCheckinResponseRequest(BaseModel):
    responses: dict[str, str]


class RoutineDiscussRequest(BaseModel):
    conversation_id: str
