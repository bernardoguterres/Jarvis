"""Phase 12B: briefing continuity — bounded snapshot audit trail, a
per-identity change-detection ledger (Home-briefing only), and local
acknowledge/snooze presentation state. Forward-only — 0001-0012 are
untouched.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefing_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("consumer", sa.String(length=24), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "consumer IN ('home', 'morning_briefing')", name="ck_briefing_snapshots_consumer_valid"
        ),
        sa.CheckConstraint(
            "trigger IN ('home_view', 'home_refresh', 'morning_briefing_manual', "
            "'morning_briefing_scheduled', 'morning_briefing_startup_catchup')",
            name="ck_briefing_snapshots_trigger_valid",
        ),
    )
    op.create_index("ix_briefing_snapshots_consumer", "briefing_snapshots", ["consumer"])
    op.create_index("ix_briefing_snapshots_generated_at", "briefing_snapshots", ["generated_at"])

    op.create_table(
        "briefing_item_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("stable_key", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("domain_slug", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_fingerprint", sa.String(length=32), nullable=True),
        sa.Column("last_title", sa.String(length=500), nullable=False),
        sa.Column("last_subtitle", sa.String(length=500), nullable=True),
        sa.Column("last_category", sa.String(length=8), nullable=True),
        sa.Column("last_link_target", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stable_key", name="uq_briefing_item_states_stable_key"),
        sa.CheckConstraint("status IN ('active', 'resolved')", name="ck_briefing_item_states_status_valid"),
    )
    op.create_index("ix_briefing_item_states_stable_key", "briefing_item_states", ["stable_key"])
    op.create_index("ix_briefing_item_states_source_type", "briefing_item_states", ["source_type"])
    op.create_index("ix_briefing_item_states_status", "briefing_item_states", ["status"])

    op.create_table(
        "briefing_acknowledgements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("stable_key", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("subtitle_snapshot", sa.String(length=500), nullable=True),
        sa.Column("domain_slug_snapshot", sa.String(length=16), nullable=True),
        sa.Column("link_target_snapshot", sa.String(length=64), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'restored')", name="ck_briefing_acknowledgements_status_valid"),
    )
    op.create_index("ix_briefing_acknowledgements_stable_key", "briefing_acknowledgements", ["stable_key"])
    op.create_index("ix_briefing_acknowledgements_fingerprint", "briefing_acknowledgements", ["fingerprint"])
    op.create_index("ix_briefing_acknowledgements_status", "briefing_acknowledgements", ["status"])
    op.create_index(
        "ix_briefing_acknowledgements_lookup", "briefing_acknowledgements", ["stable_key", "fingerprint", "status"]
    )

    op.create_table(
        "briefing_snoozes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("stable_key", sa.String(length=200), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("duration_key", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("subtitle_snapshot", sa.String(length=500), nullable=True),
        sa.Column("domain_slug_snapshot", sa.String(length=16), nullable=True),
        sa.Column("link_target_snapshot", sa.String(length=64), nullable=True),
        sa.Column("snoozed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'expired', 'restored')", name="ck_briefing_snoozes_status_valid"),
        sa.CheckConstraint(
            "duration_key IN ('1h', '4h', 'tomorrow_morning', '1w')", name="ck_briefing_snoozes_duration_valid"
        ),
    )
    op.create_index("ix_briefing_snoozes_stable_key", "briefing_snoozes", ["stable_key"])
    op.create_index("ix_briefing_snoozes_fingerprint", "briefing_snoozes", ["fingerprint"])
    op.create_index("ix_briefing_snoozes_status", "briefing_snoozes", ["status"])
    op.create_index("ix_briefing_snoozes_snooze_until", "briefing_snoozes", ["snooze_until"])
    op.create_index("ix_briefing_snoozes_lookup", "briefing_snoozes", ["stable_key", "fingerprint", "status"])


def downgrade() -> None:
    op.drop_table("briefing_snoozes")
    op.drop_table("briefing_acknowledgements")
    op.drop_table("briefing_item_states")
    op.drop_table("briefing_snapshots")
