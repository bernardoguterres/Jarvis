"""Phase 10B: controller-owned proactive routines — a fixed catalogue
(never arbitrary cron), reusing the Phase 10A scheduling infrastructure.

Routines never create action proposals, mutate Calendar, write Health
data, edit memories, send notifications, speak aloud, or contact anyone —
they only assemble a deterministic, source-backed summary from locally
cached data. No model call happens as part of running a routine; the only
model-using path is the separate, explicit "Discuss with Jarvis" action.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import _new_uuid, _utcnow

ROUTINE_TYPES = ("morning_briefing", "evening_checkin", "weekly_review")

# Domains a routine may include. BODY/MIND/PEOPLE are sensitive and must
# always be an explicit, per-routine opt-in — never included merely
# because a routine is enabled.
SENSITIVE_DOMAIN_SLUGS = ("body", "mind", "people")
ALL_DOMAIN_SLUGS = ("body", "mind", "people", "path", "build", "life")

ROUTINE_STATUSES = ("ok", "failed", "skipped")
ROUTINE_TRIGGERS = ("manual", "scheduled", "startup_catchup")
ROUTINE_OUTCOMES = ("succeeded", "failed", "skipped")

ROUTINE_RUN_RETENTION_PER_TYPE = 30


class RoutineSchedule(Base):
    """One row per fixed routine type. Disabled by default — Bernardo must
    explicitly enable and configure each one. `weekday` (0=Monday..6=Sunday)
    is only meaningful for `weekly_review`; NULL otherwise."""

    __tablename__ = "routine_schedules"
    __table_args__ = (
        CheckConstraint(f"routine_type IN {ROUTINE_TYPES}", name="ck_routine_schedules_type_valid"),
        CheckConstraint(
            f"last_status IS NULL OR last_status IN {ROUTINE_STATUSES}", name="ck_routine_schedules_status_valid"
        ),
        CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_routine_schedules_weekday_valid"),
    )

    routine_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    local_time: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")  # "HH:MM"
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    selected_domains_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    consecutive_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class RoutineRun(Base):
    """Bounded local history of routine executions. `output_json` is a
    structured, deterministic summary ({"sections": [{"title", "lines":
    [{"text", "source_ref"}]}]}) — never a raw provider payload, never
    model-generated, never a credential. `responses_json` holds the
    user's own typed answers for an Evening Check-in run (kept local,
    domain-scoped, never auto-promoted to permanent memory)."""

    __tablename__ = "routine_runs"
    __table_args__ = (
        CheckConstraint(f"routine_type IN {ROUTINE_TYPES}", name="ck_routine_runs_type_valid"),
        CheckConstraint(f"trigger IN {ROUTINE_TRIGGERS}", name="ck_routine_runs_trigger_valid"),
        CheckConstraint(f"outcome IN {ROUTINE_OUTCOMES}", name="ck_routine_runs_outcome_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    routine_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    responses_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_domains_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
