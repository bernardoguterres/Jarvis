"""Phase 4: memory items/versions, domain summaries, structured records,
context snapshots, and the FTS5 memory index.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-25

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_item_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_reason", sa.String(length=300), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "memory_item_id", "version_number", name="uq_memory_versions_item_number"
        ),
    )
    op.create_index("ix_memory_versions_memory_item_id", "memory_versions", ["memory_item_id"])

    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column(
            "domain_id", sa.String(length=36), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_message_id",
            sa.String(length=36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_conversation_id",
            sa.String(length=36),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "current_version_id",
            sa.String(length=36),
            sa.ForeignKey("memory_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "supersedes_id",
            sa.String(length=36),
            sa.ForeignKey("memory_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "superseded_by_id",
            sa.String(length=36),
            sa.ForeignKey("memory_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "scope IN ('global', 'domain')", name="ck_memory_items_scope_valid"
        ),
        sa.CheckConstraint(
            "kind IN ('identity', 'preference', 'fact', 'goal', 'constraint', 'decision', "
            "'health_context', 'relationship_context')",
            name="ck_memory_items_kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived', 'deleted')", name="ck_memory_items_status_valid"
        ),
        sa.CheckConstraint(
            "sensitivity IN ('normal', 'sensitive')", name="ck_memory_items_sensitivity_valid"
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND domain_id IS NULL) OR (scope = 'domain' AND domain_id IS NOT NULL)",
            name="ck_memory_items_scope_domain_consistency",
        ),
        sa.CheckConstraint(
            "importance >= 1 AND importance <= 5", name="ck_memory_items_importance_range"
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="ck_memory_items_confidence_range"
        ),
    )
    op.create_index("ix_memory_items_domain_id", "memory_items", ["domain_id"])

    with op.batch_alter_table("memory_versions") as batch_op:
        batch_op.create_foreign_key(
            "fk_memory_versions_memory_item_id",
            "memory_items",
            ["memory_item_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_table(
        "domain_summary_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("domain_summary_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "domain_summary_id", "version_number", name="uq_domain_summary_versions_number"
        ),
    )
    op.create_index(
        "ix_domain_summary_versions_domain_summary_id",
        "domain_summary_versions",
        ["domain_summary_id"],
    )

    op.create_table(
        "domain_summaries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "domain_id",
            sa.String(length=36),
            sa.ForeignKey("domains.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "current_version_id",
            sa.String(length=36),
            sa.ForeignKey("domain_summary_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    with op.batch_alter_table("domain_summary_versions") as batch_op:
        batch_op.create_foreign_key(
            "fk_domain_summary_versions_domain_summary_id",
            "domain_summaries",
            ["domain_summary_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_table(
        "structured_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "domain_id", sa.String(length=36), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column(
            "source_message_id",
            sa.String(length=36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "record_type IN ('body_weight', 'body_symptom', 'mind_checkin', 'people_interaction', "
            "'path_deadline', 'build_checkpoint', 'life_task')",
            name="ck_structured_records_type_valid",
        ),
        sa.CheckConstraint(
            "sensitivity IN ('normal', 'sensitive')", name="ck_structured_records_sensitivity_valid"
        ),
    )
    op.create_index("ix_structured_records_domain_id", "structured_records", ["domain_id"])
    op.create_index("ix_structured_records_record_type", "structured_records", ["record_type"])

    op.create_table(
        "context_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "active_domain_id",
            sa.String(length=36),
            sa.ForeignKey("domains.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("additional_domain_ids_json", sa.Text(), nullable=False),
        sa.Column("global_memory_version_ids_json", sa.Text(), nullable=False),
        sa.Column("domain_memory_version_ids_json", sa.Text(), nullable=False),
        sa.Column("domain_summary_version_ids_json", sa.Text(), nullable=False),
        sa.Column("structured_record_ids_json", sa.Text(), nullable=False),
        sa.Column("recent_message_ids_json", sa.Text(), nullable=False),
        sa.Column("retrieval_query", sa.Text(), nullable=False),
        sa.Column("retrieval_reasons_json", sa.Text(), nullable=False),
        sa.Column("estimated_context_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Derived, rebuildable FTS5 index over memory title/content. Never
    # authoritative — memory_items/memory_versions are the source of truth.
    op.execute(
        """
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            memory_item_id UNINDEXED,
            scope UNINDEXED,
            domain_id UNINDEXED,
            title,
            content
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory_fts")
    op.drop_table("context_snapshots")
    op.drop_index("ix_structured_records_record_type", table_name="structured_records")
    op.drop_index("ix_structured_records_domain_id", table_name="structured_records")
    op.drop_table("structured_records")
    op.drop_table("domain_summaries")
    op.drop_index(
        "ix_domain_summary_versions_domain_summary_id", table_name="domain_summary_versions"
    )
    op.drop_table("domain_summary_versions")
    op.drop_index("ix_memory_items_domain_id", table_name="memory_items")
    op.drop_table("memory_items")
    op.drop_index("ix_memory_versions_memory_item_id", table_name="memory_versions")
    op.drop_table("memory_versions")
