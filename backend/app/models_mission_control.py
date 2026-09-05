"""Mission Control / Current Focus — a bounded extension of Phase 12A-12C's
shared briefing/Mission-Focus machinery, not a second task system and not
a new phase number. Turns the existing deterministic situational
awareness into one persistent, timed focus session at a time.

Candidates are never computed here — `app/mission_control_service.py`
reuses `app/briefing_service.py`'s existing `assemble_home_briefing()`
NOW/NEXT/WATCH assembler directly. This module only owns the focus
session's own lifecycle state.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import _new_uuid, _utcnow

# The same five Mission-Focus-eligible source types
# (app/models_mission_focus.py's MISSION_FOCUS_SOURCE_TYPES) plus 'manual'
# for a freely-typed mission with no underlying source at all.
FOCUS_SESSION_SOURCE_TYPES = (
    "life_task",
    "path_deadline",
    "build_checkpoint",
    "calendar_event",
    "action_proposal",
    "manual",
)

FOCUS_SESSION_STATUSES = ("planned", "active", "paused", "completed", "abandoned")

FOCUS_SESSION_MIN_MINUTES = 5
FOCUS_SESSION_MAX_MINUTES = 180


class FocusSession(Base):
    """One focus session. `source_type`/`source_id` are a typed pointer to
    a real, already-existing source (never a copy of its content) exactly
    like `MissionFocusPin` — `source_type='manual'` is the one exception,
    for a freely-typed mission with `source_id=None`. `domain_id` is
    always resolved server-side from the real source when one exists
    (never accepted from the client for anything but a manual mission,
    where Bernardo is explicitly choosing it himself).

    The timer is derived, never stored as a running countdown:
    `started_at`, `paused_at` (set only while currently paused),
    `accumulated_paused_seconds` (total paused time from all *earlier*
    pause/resume cycles), and `completed_at` are the only facts persisted;
    `app/mission_control_service.py::elapsed_seconds()` computes elapsed
    focus time from them at read time, exactly the pattern this project
    already uses for `IntegrationSyncSchedule.next_due_at` and the routine
    scheduler — never a decrementing frontend interval as the source of
    truth, so a restart is always accurate for free.

    Only one row may have `status` in `('active', 'paused')` at a time —
    enforced by `uq_focus_sessions_one_in_flight` (migration 0015), a
    partial unique index on a constant expression, not just an
    application-level check, so a race can never bypass it."""

    __tablename__ = "focus_sessions"
    __table_args__ = (
        CheckConstraint(f"source_type IN {FOCUS_SESSION_SOURCE_TYPES}", name="ck_focus_sessions_source_type_valid"),
        CheckConstraint(f"status IN {FOCUS_SESSION_STATUSES}", name="ck_focus_sessions_status_valid"),
        CheckConstraint(
            f"target_duration_minutes >= {FOCUS_SESSION_MIN_MINUTES} "
            f"AND target_duration_minutes <= {FOCUS_SESSION_MAX_MINUTES}",
            name="ck_focus_sessions_duration_bounded",
        ),
        CheckConstraint("accumulated_paused_seconds >= 0", name="ck_focus_sessions_paused_seconds_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("domains.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_title_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned", index=True)
    target_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accumulated_paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    what_changed_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Set only when this row was force-ended by a restore into a
    # (possibly different) installation — never by a genuine user abandon.
    abandoned_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
