"""Phase 10: controller-owned automatic integration resync — persistent
per-provider schedule configuration and a bounded local sync-run history.

Nothing here is a Hermes cron, a Hermes skill, or a sub-agent — this is a
plain in-process background loop (see app/scheduler_service.py and
app/scheduler_runtime.py) started/stopped by FastAPI's own lifespan.
Automatic work only ever happens while this backend process is running.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import _new_uuid, _utcnow

SCHEDULABLE_PROVIDERS = ("google_calendar", "google_health")

# Provider-specific selectable cadences (minutes) and the minimum interval
# enforced server-side — never trust the UI alone to prevent hammering
# either API.
ALLOWED_INTERVAL_MINUTES = {
    "google_calendar": (15, 30, 60),
    "google_health": (60, 180, 360, 1440),
}
MIN_INTERVAL_MINUTES = {
    "google_calendar": 15,
    "google_health": 60,
}
DEFAULT_INTERVAL_MINUTES = {
    "google_calendar": 30,
    "google_health": 360,
}

SYNC_STATUSES = ("ok", "partial", "failed", "skipped", "reconnect_required")
SYNC_TRIGGERS = ("manual", "scheduled", "startup_catchup")
SYNC_OUTCOMES = ("succeeded", "partial", "failed", "skipped")

# How many recent runs to keep per provider — a bounded local audit trail,
# not an ever-growing log. Enforced by scheduler_service.py on every insert.
SYNC_RUN_RETENTION_PER_PROVIDER = 50


class IntegrationSyncSchedule(Base):
    """One row per schedulable provider. Disabled by default — Bernardo
    must explicitly enable automatic sync per provider through the
    Integrations Centre; nothing here is ever turned on by Jarvis itself."""

    __tablename__ = "integration_sync_schedules"
    __table_args__ = (
        CheckConstraint(f"provider IN {SCHEDULABLE_PROVIDERS}", name="ck_integration_sync_schedules_provider_valid"),
        CheckConstraint(
            f"last_status IS NULL OR last_status IN {SYNC_STATUSES}",
            name="ck_integration_sync_schedules_status_valid",
        ),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class IntegrationSyncRun(Base):
    """Bounded local audit trail of sync attempts — provider, what
    triggered it, timing, outcome, a sanitized reason (never a raw
    provider payload, token, or other secret), and non-sensitive result
    counts only (e.g. {"events": 3}, never event titles/content)."""

    __tablename__ = "integration_sync_runs"
    __table_args__ = (
        CheckConstraint(f"provider IN {SCHEDULABLE_PROVIDERS}", name="ck_integration_sync_runs_provider_valid"),
        CheckConstraint(f"trigger IN {SYNC_TRIGGERS}", name="ck_integration_sync_runs_trigger_valid"),
        CheckConstraint(f"outcome IN {SYNC_OUTCOMES}", name="ck_integration_sync_runs_outcome_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
