"""Phase 8: action proposals, audit events, hook events, and versioned
skills.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("capability_id", sa.String(length=64), nullable=False),
        sa.Column(
            "domain_id", sa.String(length=36), sa.ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("permission_level", sa.String(length=16), nullable=False),
        sa.Column("arguments_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_effect", sa.Text(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("confirmation_token", sa.String(length=64), nullable=True),
        sa.Column("confirmation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability_id IN ('memory.create', 'structured_record.create', 'domain_summary.update')",
            name="ck_action_proposals_capability_valid",
        ),
        sa.CheckConstraint(
            "permission_level IN ('read', 'draft', 'confirm', 'execute')",
            name="ck_action_proposals_permission_valid",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'denied', 'expired', 'executing', 'succeeded', 'failed')",
            name="ck_action_proposals_status_valid",
        ),
    )
    op.create_index("ix_action_proposals_domain_id", "action_proposals", ["domain_id"])
    op.create_index("ix_action_proposals_status", "action_proposals", ["status"])

    op.create_table(
        "action_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "action_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("action_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_action_audit_events_action_proposal_id", "action_audit_events", ["action_proposal_id"]
    )

    op.create_table(
        "hook_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("hook_name", sa.String(length=128), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column(
            "action_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("action_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "phase IN ('before_context', 'before_action', 'after_action', 'on_failure')",
            name="ck_hook_events_phase_valid",
        ),
        sa.CheckConstraint("outcome IN ('ok', 'blocked', 'error')", name="ck_hook_events_outcome_valid"),
    )
    op.create_index("ix_hook_events_action_proposal_id", "hook_events", ["action_proposal_id"])

    # Circular FK (skills <-> skill_versions), same pattern as
    # memory_items/memory_versions in 0003: create skill_versions without
    # its skill_id FK first, then skills, then add the FK back via batch_alter_table.
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("workflow_steps_json", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_skill_number"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])

    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "domain_id", sa.String(length=36), sa.ForeignKey("domains.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("invocation_phrases_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "current_version_id",
            sa.String(length=36),
            sa.ForeignKey("skill_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_skills_status_valid"),
        sa.CheckConstraint("created_by IN ('user', 'jarvis')", name="ck_skills_created_by_valid"),
    )
    op.create_index("ix_skills_slug", "skills", ["slug"])
    op.create_index("ix_skills_domain_id", "skills", ["domain_id"])

    with op.batch_alter_table("skill_versions") as batch_op:
        batch_op.create_foreign_key(
            "fk_skill_versions_skill_id", "skills", ["skill_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    op.drop_table("skills")
    op.drop_index("ix_skill_versions_skill_id", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index("ix_hook_events_action_proposal_id", table_name="hook_events")
    op.drop_table("hook_events")
    op.drop_index("ix_action_audit_events_action_proposal_id", table_name="action_audit_events")
    op.drop_table("action_audit_events")
    op.drop_index("ix_action_proposals_status", table_name="action_proposals")
    op.drop_index("ix_action_proposals_domain_id", table_name="action_proposals")
    op.drop_table("action_proposals")
