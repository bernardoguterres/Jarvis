"""Phase 12D... no — Mission Control / Current Focus, a bounded extension of
Phase 12A-12C's shared briefing/Mission-Focus machinery, not a new phase
number and not a second task system. Adds one table, `focus_sessions`,
for a single-active-session focus timer whose candidates are drawn from
the existing NOW/NEXT/WATCH briefing assembler.

A partial unique index (`uq_focus_sessions_one_in_flight`, on a constant
expression, `WHERE status IN ('active', 'paused')`) gives real
database-level enforcement of "at most one active-or-paused session at a
time" — for both INSERT and UPDATE — closing the same class of race a
plain application-level check-then-write cannot fully close alone,
exactly the reasoning already established for Phase 12C's 5-pin limit
(migration 0014).

Forward-only — 0001-0014 are untouched.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-30

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "focus_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("domain_id", sa.String(length=36), nullable=True),
        # The same five Mission-Focus-eligible source types
        # (app/models_mission_focus.py's MISSION_FOCUS_SOURCE_TYPES), plus
        # 'manual' for a freely-typed mission with no underlying source.
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("source_title_snapshot", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("target_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accumulated_paused_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.String(length=1000), nullable=True),
        sa.Column("what_changed_note", sa.String(length=1000), nullable=True),
        # Set only when this row was force-ended by a restore into a
        # (possibly different) installation, never by a genuine user
        # abandon — see app/import_service.py's _interrupt_active_focus_sessions.
        sa.Column("abandoned_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"]),
        sa.CheckConstraint(
            "source_type IN ('life_task', 'path_deadline', 'build_checkpoint', 'calendar_event', "
            "'action_proposal', 'manual')",
            name="ck_focus_sessions_source_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'paused', 'completed', 'abandoned')",
            name="ck_focus_sessions_status_valid",
        ),
        sa.CheckConstraint(
            "target_duration_minutes >= 5 AND target_duration_minutes <= 180",
            name="ck_focus_sessions_duration_bounded",
        ),
        sa.CheckConstraint("accumulated_paused_seconds >= 0", name="ck_focus_sessions_paused_seconds_non_negative"),
    )
    op.create_index("ix_focus_sessions_domain_id", "focus_sessions", ["domain_id"])
    op.create_index("ix_focus_sessions_source", "focus_sessions", ["source_type", "source_id"])
    op.create_index("ix_focus_sessions_status", "focus_sessions", ["status"])
    op.create_index("ix_focus_sessions_created_at", "focus_sessions", ["created_at"])

    op.execute(
        "CREATE UNIQUE INDEX uq_focus_sessions_one_in_flight ON focus_sessions((1)) "
        "WHERE status IN ('active', 'paused')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_focus_sessions_one_in_flight")
    op.drop_index("ix_focus_sessions_created_at", table_name="focus_sessions")
    op.drop_index("ix_focus_sessions_status", table_name="focus_sessions")
    op.drop_index("ix_focus_sessions_source", table_name="focus_sessions")
    op.drop_index("ix_focus_sessions_domain_id", table_name="focus_sessions")
    op.drop_table("focus_sessions")
