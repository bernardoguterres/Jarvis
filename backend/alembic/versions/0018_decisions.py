"""Phase 12F: Evidence-Based Decision Room — the final planned major V1
feature, completing Recall -> Research -> Decide -> Focus. Built entirely
on top of Phase 12D Unified Recall and Phase 12E Research Workspaces —
never a parallel search/evidence system. Adds eight new tables:
decisions, decision_options, decision_criteria, decision_assessments,
decision_evidence_links, decision_factors (assumptions/risks/unknowns),
decision_brief_versions (deterministic snapshot + optional model
critique), decision_final_versions (the user's actual recorded decision,
always separate from any brief/critique), and decision_outcome_reviews.

`decision_evidence_links.source_type` intentionally allows one more value
("decision") than migration 0017's already-shipped, unmodifiable
`research_evidence.source_type` CHECK constraint — see
app/schemas_decisions.py's own comment for why this is a deliberate,
documented divergence (a decision may cite another decision as evidence;
research_evidence's frozen constraint from before Decisions existed
cannot retroactively gain that value without editing an existing
migration, which CLAUDE.md forbids).

Forward-only — 0001-0017 are untouched.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("domain_id", sa.String(length=36), sa.ForeignKey("domains.id"), nullable=True),
        sa.Column(
            "research_workspace_id", sa.String(length=36), sa.ForeignKey("research_workspaces.id"), nullable=True
        ),
        sa.Column("included_domain_slugs_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cost_of_delay_note", sa.Text(), nullable=True),
        sa.Column("info_confidence", sa.Integer(), nullable=True),
        sa.Column("reversibility", sa.String(length=24), nullable=True),
        sa.Column("supersedes_decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=True),
        sa.Column(
            "superseded_by_decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=True
        ),
        sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandoned_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'evaluating', 'decided', 'reopened', 'superseded', 'abandoned')",
            name="ck_decisions_status_valid",
        ),
        sa.CheckConstraint(
            "info_confidence IS NULL OR (info_confidence >= 1 AND info_confidence <= 5)",
            name="ck_decisions_info_confidence_range",
        ),
        sa.CheckConstraint(
            "reversibility IS NULL OR reversibility IN ('easily_reversible', 'hard_to_reverse', 'irreversible')",
            name="ck_decisions_reversibility_valid",
        ),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])
    op.create_index("ix_decisions_domain_id", "decisions", ["domain_id"])
    op.create_index("ix_decisions_research_workspace_id", "decisions", ["research_workspace_id"])

    op.create_table(
        "decision_options",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("benefits", sa.Text(), nullable=True),
        sa.Column("costs", sa.Text(), nullable=True),
        sa.Column("risks", sa.Text(), nullable=True),
        sa.Column("reversibility", sa.String(length=24), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'eliminated', 'chosen')", name="ck_decision_options_status_valid"),
        sa.CheckConstraint(
            "reversibility IS NULL OR reversibility IN ('easily_reversible', 'hard_to_reverse', 'irreversible')",
            name="ck_decision_options_reversibility_valid",
        ),
    )
    op.create_index("ix_decision_options_decision_id", "decision_options", ["decision_id"])

    op.create_table(
        "decision_criteria",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("weight >= 1 AND weight <= 5", name="ck_decision_criteria_weight_range"),
    )
    op.create_index("ix_decision_criteria_decision_id", "decision_criteria", ["decision_id"])

    op.create_table(
        "decision_assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("option_id", sa.String(length=36), sa.ForeignKey("decision_options.id"), nullable=False),
        sa.Column("criterion_id", sa.String(length=36), sa.ForeignKey("decision_criteria.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)", name="ck_decision_assessments_score_range"
        ),
        sa.UniqueConstraint("option_id", "criterion_id", name="uq_decision_assessments_option_criterion"),
    )
    op.create_index("ix_decision_assessments_decision_id", "decision_assessments", ["decision_id"])

    op.create_table(
        "decision_evidence_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column(
            "research_evidence_id", sa.String(length=36), sa.ForeignKey("research_evidence.id"), nullable=True
        ),
        sa.Column(
            "linked_option_id", sa.String(length=36), sa.ForeignKey("decision_options.id"), nullable=True
        ),
        sa.Column("domain_slug", sa.String(length=16), nullable=True),
        sa.Column("title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("snippet_snapshot", sa.Text(), nullable=False),
        sa.Column("occurred_at_snapshot", sa.String(length=40), nullable=True),
        sa.Column("stance", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_type IN ('conversation', 'message', 'memory_item', 'structured_record', "
            "'domain_summary', 'document', 'document_chunk', 'calendar_event', 'action_proposal', "
            "'routine_run', 'mission_control_session', 'decision')",
            name="ck_decision_evidence_links_source_type_valid",
        ),
        sa.CheckConstraint(
            "stance IN ('supporting', 'contradicting', 'contextual', 'unresolved')",
            name="ck_decision_evidence_links_stance_valid",
        ),
        sa.CheckConstraint("status IN ('active', 'removed')", name="ck_decision_evidence_links_status_valid"),
    )
    op.create_index("ix_decision_evidence_links_decision_id", "decision_evidence_links", ["decision_id"])
    op.create_index("ix_decision_evidence_links_source_type", "decision_evidence_links", ["source_type"])
    op.create_index("ix_decision_evidence_links_source_id", "decision_evidence_links", ["source_id"])
    op.create_index("ix_decision_evidence_links_status", "decision_evidence_links", ["status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_decision_evidence_links_active_source "
        "ON decision_evidence_links(decision_id, source_type, source_id) WHERE status = 'active'"
    )

    op.create_table(
        "decision_factors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "linked_option_id", sa.String(length=36), sa.ForeignKey("decision_options.id"), nullable=True
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('assumption', 'risk', 'unknown')", name="ck_decision_factors_kind_valid"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="ck_decision_factors_status_valid"),
    )
    op.create_index("ix_decision_factors_decision_id", "decision_factors", ["decision_id"])
    op.create_index("ix_decision_factors_kind", "decision_factors", ["kind"])

    op.create_table(
        "decision_brief_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
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
        sa.CheckConstraint("source IN ('deterministic', 'model')", name="ck_decision_brief_versions_source_valid"),
        sa.CheckConstraint(
            "status IN ('ok', 'invalid_citations')", name="ck_decision_brief_versions_status_valid"
        ),
        sa.UniqueConstraint("decision_id", "version_number", name="uq_decision_brief_versions_decision_version"),
    )
    op.create_index("ix_decision_brief_versions_decision_id", "decision_brief_versions", ["decision_id"])

    op.create_table(
        "decision_final_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "selected_option_id", sa.String(length=36), sa.ForeignKey("decision_options.id"), nullable=False
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decision_confidence", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_confidence >= 1 AND decision_confidence <= 5",
            name="ck_decision_final_versions_confidence_range",
        ),
        sa.UniqueConstraint("decision_id", "version_number", name="uq_decision_final_versions_decision_version"),
    )
    op.create_index("ix_decision_final_versions_decision_id", "decision_final_versions", ["decision_id"])

    op.create_table(
        "decision_outcome_reviews",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("decision_id", sa.String(length=36), sa.ForeignKey("decisions.id"), nullable=False),
        sa.Column(
            "decision_final_version_id",
            sa.String(length=36),
            sa.ForeignKey("decision_final_versions.id"),
            nullable=False,
        ),
        sa.Column("what_happened", sa.Text(), nullable=False),
        sa.Column("intended_outcome_achieved", sa.Boolean(), nullable=True),
        sa.Column("confidence_was_appropriate", sa.Boolean(), nullable=True),
        sa.Column("would_decide_same_again", sa.Boolean(), nullable=True),
        sa.Column("lessons_learned", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_outcome_reviews_decision_id", "decision_outcome_reviews", ["decision_id"])

    # recall_fts (migration 0016) gains one more indexable source_type,
    # "decision" — no schema change to recall_fts itself (it has no
    # source_type CHECK constraint), only app/recall_index_service.py's
    # RECALL_SOURCE_TYPES tuple (Python-level) needs it.


def downgrade() -> None:
    op.drop_index("ix_decision_outcome_reviews_decision_id", table_name="decision_outcome_reviews")
    op.drop_table("decision_outcome_reviews")

    op.drop_index("ix_decision_final_versions_decision_id", table_name="decision_final_versions")
    op.drop_table("decision_final_versions")

    op.drop_index("ix_decision_brief_versions_decision_id", table_name="decision_brief_versions")
    op.drop_table("decision_brief_versions")

    op.drop_index("ix_decision_factors_kind", table_name="decision_factors")
    op.drop_index("ix_decision_factors_decision_id", table_name="decision_factors")
    op.drop_table("decision_factors")

    op.execute("DROP INDEX IF EXISTS uq_decision_evidence_links_active_source")
    op.drop_index("ix_decision_evidence_links_status", table_name="decision_evidence_links")
    op.drop_index("ix_decision_evidence_links_source_id", table_name="decision_evidence_links")
    op.drop_index("ix_decision_evidence_links_source_type", table_name="decision_evidence_links")
    op.drop_index("ix_decision_evidence_links_decision_id", table_name="decision_evidence_links")
    op.drop_table("decision_evidence_links")

    op.drop_index("ix_decision_assessments_decision_id", table_name="decision_assessments")
    op.drop_table("decision_assessments")

    op.drop_index("ix_decision_criteria_decision_id", table_name="decision_criteria")
    op.drop_table("decision_criteria")

    op.drop_index("ix_decision_options_decision_id", table_name="decision_options")
    op.drop_table("decision_options")

    op.drop_index("ix_decisions_research_workspace_id", table_name="decisions")
    op.drop_index("ix_decisions_domain_id", table_name="decisions")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_table("decisions")
