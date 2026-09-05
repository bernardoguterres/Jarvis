"""Phase 12C: Mission Focus — a small, deliberate, user-owned watchlist of
at most five pinned references to existing sources (LIFE tasks, PATH
deadlines, BUILD checkpoints, selected Calendar events, unresolved action
proposals). Forward-only — 0001-0013 are untouched.

Two partial unique indexes and a pair of triggers give this real
database-level enforcement rather than relying on application code alone:
* `uq_mission_focus_active_source` — at most one *active* pin per
  (source_type, source_id).
* `uq_mission_focus_active_rank` — at most one *active* pin per rank.
* `trg_mission_focus_max_active_pins_insert` / `..._update` — refuse an
  INSERT or an UPDATE that would make status='active' while 5 active pins
  already exist, closing the race a plain application-level count-then-
  insert check cannot fully close on its own.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mission_focus_pins",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("domain_slug", sa.String(length=16), nullable=True),
        sa.Column("source_title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("next_action", sa.String(length=300), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocker", sa.String(length=300), nullable=True),
        sa.Column("source_fingerprint_at_pin", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unpinned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('life_task', 'path_deadline', 'build_checkpoint', 'calendar_event', 'action_proposal')",
            name="ck_mission_focus_pins_source_type_valid",
        ),
        sa.CheckConstraint("status IN ('active', 'unpinned')", name="ck_mission_focus_pins_status_valid"),
        # Only a lower bound at the database level — see
        # app/models_mission_focus.py's MissionFocusPin docstring for why
        # the full 1-5 range is enforced at the service layer instead.
        sa.CheckConstraint("rank >= 1", name="ck_mission_focus_pins_rank_positive"),
    )
    op.create_index("ix_mission_focus_pins_source_type", "mission_focus_pins", ["source_type"])
    op.create_index("ix_mission_focus_pins_source_id", "mission_focus_pins", ["source_id"])
    op.create_index("ix_mission_focus_pins_status", "mission_focus_pins", ["status"])

    op.execute(
        "CREATE UNIQUE INDEX uq_mission_focus_active_source ON mission_focus_pins(source_type, source_id) "
        "WHERE status = 'active'"
    )
    op.execute("CREATE UNIQUE INDEX uq_mission_focus_active_rank ON mission_focus_pins(rank) WHERE status = 'active'")

    op.execute(
        """
        CREATE TRIGGER trg_mission_focus_max_active_pins_insert
        BEFORE INSERT ON mission_focus_pins
        WHEN NEW.status = 'active'
          AND (SELECT COUNT(*) FROM mission_focus_pins WHERE status = 'active') >= 5
        BEGIN
            SELECT RAISE(ABORT, 'Mission Focus already has 5 active pins.');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_mission_focus_max_active_pins_update
        BEFORE UPDATE OF status ON mission_focus_pins
        WHEN NEW.status = 'active' AND OLD.status != 'active'
          AND (SELECT COUNT(*) FROM mission_focus_pins WHERE status = 'active') >= 5
        BEGIN
            SELECT RAISE(ABORT, 'Mission Focus already has 5 active pins.');
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_mission_focus_max_active_pins_update")
    op.execute("DROP TRIGGER IF EXISTS trg_mission_focus_max_active_pins_insert")
    op.execute("DROP INDEX IF EXISTS uq_mission_focus_active_rank")
    op.execute("DROP INDEX IF EXISTS uq_mission_focus_active_source")
    op.drop_index("ix_mission_focus_pins_status", table_name="mission_focus_pins")
    op.drop_index("ix_mission_focus_pins_source_id", table_name="mission_focus_pins")
    op.drop_index("ix_mission_focus_pins_source_type", table_name="mission_focus_pins")
    op.drop_table("mission_focus_pins")
