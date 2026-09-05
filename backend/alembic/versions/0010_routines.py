"""Phase 10B: controller-owned proactive routines — a fixed catalogue
(morning_briefing, evening_checkin, weekly_review), reusing the Phase 10A
scheduling infrastructure. Forward-only — 0001-0009 are untouched.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-27

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routine_schedules",
        sa.Column("routine_type", sa.String(length=32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("local_time", sa.String(length=5), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("selected_domains_json", sa.Text(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "routine_type IN ('morning_briefing', 'evening_checkin', 'weekly_review')",
            name="ck_routine_schedules_type_valid",
        ),
        sa.CheckConstraint(
            "last_status IS NULL OR last_status IN ('ok', 'failed', 'skipped')",
            name="ck_routine_schedules_status_valid",
        ),
        sa.CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_routine_schedules_weekday_valid"),
    )

    op.create_table(
        "routine_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("routine_type", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("responses_json", sa.Text(), nullable=True),
        sa.Column("selected_domains_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "routine_type IN ('morning_briefing', 'evening_checkin', 'weekly_review')",
            name="ck_routine_runs_type_valid",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled', 'startup_catchup')", name="ck_routine_runs_trigger_valid"
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'skipped')", name="ck_routine_runs_outcome_valid"
        ),
    )
    op.create_index("ix_routine_runs_routine_type", "routine_runs", ["routine_type"])

    # All three routines start disabled — Bernardo must explicitly enable
    # and configure each one; nothing here is ever turned on automatically.
    op.execute(
        "INSERT INTO routine_schedules "
        "(routine_type, enabled, local_time, weekday, timezone, selected_domains_json, consecutive_failure_count, created_at, updated_at) VALUES "
        "('morning_briefing', 0, '08:00', NULL, 'UTC', '[]', 0, datetime('now'), datetime('now')), "
        "('evening_checkin', 0, '20:00', NULL, 'UTC', '[]', 0, datetime('now'), datetime('now')), "
        "('weekly_review', 0, '09:00', 6, 'UTC', '[]', 0, datetime('now'), datetime('now'))"
    )


def downgrade() -> None:
    op.drop_index("ix_routine_runs_routine_type", table_name="routine_runs")
    op.drop_table("routine_runs")
    op.drop_table("routine_schedules")
