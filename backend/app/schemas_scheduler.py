"""Phase 10: request/response models for per-provider automatic-sync
schedule configuration and the bounded local sync-run history. Never
includes a credential — schedule configuration has no secret of its own."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IntegrationScheduleRead(BaseModel):
    provider: str
    enabled: bool
    interval_minutes: int
    next_due_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_status: str | None
    last_error: str | None
    consecutive_failure_count: int


class IntegrationScheduleUpdateRequest(BaseModel):
    enabled: bool
    interval_minutes: int


class IntegrationSyncRunRead(BaseModel):
    id: str
    provider: str
    trigger: str
    started_at: datetime
    completed_at: datetime | None
    outcome: str
    reason: str | None
    result_summary: dict
