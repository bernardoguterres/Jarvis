"""Phase 12E: Source-Grounded Research Workspace, built on top of Phase
12D Unified Recall — never a second search/indexing engine. Adds four new
tables: research_workspaces, research_evidence (a typed pointer to a real,
already-existing Recall-eligible source, never a copy of its live
content), research_notes (user-authored notes/claims), and
research_brief_versions (versioned, cited briefs — regenerating always
creates a new version rather than overwriting one).

A partial unique index (`uq_research_evidence_active_source`) makes adding
the same evidence to a workspace twice idempotent even under a race,
mirroring migration 0014's `uq_mission_focus_active_source` pattern. A
plain unique constraint on (workspace_id, version_number) keeps brief
version numbering unambiguous per workspace.

Forward-only — 0001-0016 are untouched.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("domain_id", sa.String(length=36), sa.ForeignKey("domains.id"), nullable=True),
        sa.Column("included_domain_slugs_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_research_workspaces_status_valid"),
    )
    op.create_index("ix_research_workspaces_status", "research_workspaces", ["status"])

    op.create_table(
        "research_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36), sa.ForeignKey("research_workspaces.id"), nullable=False
        ),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("domain_slug", sa.String(length=16), nullable=True),
        sa.Column("title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("snippet_snapshot", sa.Text(), nullable=False),
        sa.Column("occurred_at_snapshot", sa.String(length=40), nullable=True),
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('conversation', 'message', 'memory_item', 'structured_record', "
            "'domain_summary', 'document', 'document_chunk', 'calendar_event', 'action_proposal', "
            "'routine_run', 'mission_control_session')",
            name="ck_research_evidence_source_type_valid",
        ),
        sa.CheckConstraint(
            "classification IN ('supporting', 'contradicting', 'contextual', 'unresolved')",
            name="ck_research_evidence_classification_valid",
        ),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_research_evidence_status_valid"),
    )
    op.create_index("ix_research_evidence_workspace_id", "research_evidence", ["workspace_id"])
    op.create_index("ix_research_evidence_source_type", "research_evidence", ["source_type"])
    op.create_index("ix_research_evidence_source_id", "research_evidence", ["source_id"])
    op.create_index("ix_research_evidence_status", "research_evidence", ["status"])
    # Real database-level idempotency: adding the same (workspace, source)
    # pair twice can never create two simultaneously-active evidence rows,
    # even under a race the service layer's own check-then-insert alone
    # cannot fully close — mirrors migration 0014's
    # uq_mission_focus_active_source pattern exactly. Partial (not plain)
    # so re-adding a previously-removed evidence row is never wrongly
    # blocked by its own old 'removed' row.
    op.execute(
        "CREATE UNIQUE INDEX uq_research_evidence_active_source "
        "ON research_evidence(workspace_id, source_type, source_id) WHERE status = 'active'"
    )

    op.create_table(
        "research_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36), sa.ForeignKey("research_workspaces.id"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("linked_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_research_notes_status_valid"),
    )
    op.create_index("ix_research_notes_workspace_id", "research_notes", ["workspace_id"])
    op.create_index("ix_research_notes_status", "research_notes", ["status"])

    op.create_table(
        "research_brief_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(length=36), sa.ForeignKey("research_workspaces.id"), nullable=False
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("sections_json", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("model_meta_json", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('deterministic', 'model')", name="ck_research_brief_versions_source_valid"),
        sa.CheckConstraint(
            "status IN ('ok', 'invalid_citations')", name="ck_research_brief_versions_status_valid"
        ),
        sa.UniqueConstraint(
            "workspace_id", "version_number", name="uq_research_brief_versions_workspace_version"
        ),
    )
    op.create_index("ix_research_brief_versions_workspace_id", "research_brief_versions", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_research_brief_versions_workspace_id", table_name="research_brief_versions")
    op.drop_table("research_brief_versions")

    op.drop_index("ix_research_notes_status", table_name="research_notes")
    op.drop_index("ix_research_notes_workspace_id", table_name="research_notes")
    op.drop_table("research_notes")

    op.execute("DROP INDEX IF EXISTS uq_research_evidence_active_source")
    op.drop_index("ix_research_evidence_status", table_name="research_evidence")
    op.drop_index("ix_research_evidence_source_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_source_type", table_name="research_evidence")
    op.drop_index("ix_research_evidence_workspace_id", table_name="research_evidence")
    op.drop_table("research_evidence")

    op.drop_index("ix_research_workspaces_status", table_name="research_workspaces")
    op.drop_table("research_workspaces")
