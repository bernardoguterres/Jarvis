"""Phase 10: controller-owned automatic integration resync. Adds
per-provider schedule configuration (disabled by default) and a bounded
local sync-run history. Forward-only — 0001-0008 are untouched.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-27

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_sync_schedules",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('google_calendar', 'google_health')",
            name="ck_integration_sync_schedules_provider_valid",
        ),
        sa.CheckConstraint(
            "last_status IS NULL OR last_status IN ('ok', 'partial', 'failed', 'skipped', 'reconnect_required')",
            name="ck_integration_sync_schedules_status_valid",
        ),
    )

    op.create_table(
        "integration_sync_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("result_summary_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "provider IN ('google_calendar', 'google_health')",
            name="ck_integration_sync_runs_provider_valid",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled', 'startup_catchup')",
            name="ck_integration_sync_runs_trigger_valid",
        ),
        sa.CheckConstraint(
            "outcome IN ('succeeded', 'partial', 'failed', 'skipped')",
            name="ck_integration_sync_runs_outcome_valid",
        ),
    )
    op.create_index("ix_integration_sync_runs_provider", "integration_sync_runs", ["provider"])

    # Both schedules start disabled — Bernardo must explicitly enable each
    # one; nothing here is ever turned on automatically by this migration.
    op.execute(
        "INSERT INTO integration_sync_schedules "
        "(provider, enabled, interval_minutes, consecutive_failure_count, created_at, updated_at) VALUES "
        "('google_calendar', 0, 30, 0, datetime('now'), datetime('now')), "
        "('google_health', 0, 360, 0, datetime('now'), datetime('now'))"
    )


def downgrade() -> None:
    op.drop_index("ix_integration_sync_runs_provider", table_name="integration_sync_runs")
    op.drop_table("integration_sync_runs")
    op.drop_table("integration_sync_schedules")
