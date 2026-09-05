"""Phase 12F: Evidence-Based Decision Room — the final planned major V1
feature, completing Recall -> Research -> Decide -> Focus. Built entirely
on Phase 12D Unified Recall and Phase 12E Research Workspaces: evidence
discovery/availability reuses `app.recall_service` directly, and a
Decision may link one Research workspace plus individually-selected
Research evidence — never a parallel search or evidence system.

Jarvis supports the decision; it never makes it. `DecisionFinalVersion`
rows are only ever created by an explicit user action
(`app.decision_service.decide`) — a `DecisionBriefVersion` with
`source='model'` is a critique/recommendation only, structurally a
different table, never capable of transitioning a Decision's lifecycle.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import _new_uuid, _utcnow

DECISION_STATUSES = ("draft", "evaluating", "decided", "reopened", "superseded", "abandoned")
# Statuses in which options/criteria/assessments/evidence/factors/the
# decision's own framing fields may still be edited — mirrors the
# explicit "reopen is the only path back to editable" rule: once decided,
# the record that produced that decision is frozen until reopened.
DECISION_EDITABLE_STATUSES = ("draft", "evaluating", "reopened")

REVERSIBILITY_LEVELS = ("easily_reversible", "hard_to_reverse", "irreversible")

DECISION_OPTION_STATUSES = ("active", "eliminated", "chosen")

DECISION_ASSESSMENT_SCORE_MIN = 1
DECISION_ASSESSMENT_SCORE_MAX = 5
DECISION_CRITERION_WEIGHT_MIN = 1
DECISION_CRITERION_WEIGHT_MAX = 5

# The same source-type vocabulary Recall itself indexes, plus "decision"
# itself (a decision may cite another decision as evidence) — see the
# module docstring for why this deliberately diverges from
# app.models_research.RESEARCH_EVIDENCE_SOURCE_TYPES by one value.
DECISION_EVIDENCE_SOURCE_TYPES = (
    "conversation",
    "message",
    "memory_item",
    "structured_record",
    "domain_summary",
    "document",
    "document_chunk",
    "calendar_event",
    "action_proposal",
    "routine_run",
    "mission_control_session",
    "decision",
)
DECISION_EVIDENCE_STANCES = ("supporting", "contradicting", "contextual", "unresolved")
DECISION_EVIDENCE_STATUSES = ("active", "removed")

DECISION_FACTOR_KINDS = ("assumption", "risk", "unknown")
DECISION_FACTOR_STATUSES = ("open", "resolved")

DECISION_BRIEF_SOURCES = ("deterministic", "model")
DECISION_BRIEF_STATUSES = ("ok", "invalid_citations")


class Decision(Base):
    """One decision under consideration. `included_domain_slugs_json`
    mirrors ResearchWorkspace's own domain-policy field exactly — default
    LIFE/PATH/BUILD, an explicit empty list honored literally. When
    `research_workspace_id` links a Research workspace, the *effective*
    domain policy for evidence discovery/linking is always the
    intersection of this decision's own policy and that workspace's
    (`app.decision_service._effective_domain_slugs`) — computed fresh at
    read/write time, never stored, never the union."""

    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(f"status IN {DECISION_STATUSES}", name="ck_decisions_status_valid"),
        CheckConstraint(
            "info_confidence IS NULL OR (info_confidence >= 1 AND info_confidence <= 5)",
            name="ck_decisions_info_confidence_range",
        ),
        CheckConstraint(
            f"reversibility IS NULL OR reversibility IN {REVERSIBILITY_LEVELS}",
            name="ck_decisions_reversibility_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("domains.id"), nullable=True)
    research_workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_workspaces.id"), nullable=True
    )
    included_domain_slugs_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cost_of_delay_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    info_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reversibility: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # Bidirectional supersede link — the same pattern app/models.py's
    # MemoryItem.supersedes_id/superseded_by_id already established.
    supersedes_decision_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=True)
    superseded_by_decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id"), nullable=True
    )
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    abandoned_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    options: Mapped[list["DecisionOption"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan", foreign_keys="DecisionOption.decision_id"
    )
    criteria: Mapped[list["DecisionCriterion"]] = relationship(back_populates="decision", cascade="all, delete-orphan")
    evidence_links: Mapped[list["DecisionEvidenceLink"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    factors: Mapped[list["DecisionFactor"]] = relationship(back_populates="decision", cascade="all, delete-orphan")
    brief_versions: Mapped[list["DecisionBriefVersion"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )
    final_versions: Mapped[list["DecisionFinalVersion"]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )


class DecisionOption(Base):
    """One option under consideration. `reversibility` here is specific to
    choosing *this* option (distinct from `Decision.reversibility`, an
    overall/default judgment that may predate any option-level detail).
    `status='chosen'` is set only by `app.decision_service.decide` on the
    selected option — never implies the decision itself is final on its
    own (a chosen option with no `DecisionFinalVersion` row is not a
    decision)."""

    __tablename__ = "decision_options"
    __table_args__ = (
        CheckConstraint(f"status IN {DECISION_OPTION_STATUSES}", name="ck_decision_options_status_valid"),
        CheckConstraint(
            f"reversibility IS NULL OR reversibility IN {REVERSIBILITY_LEVELS}",
            name="ck_decision_options_reversibility_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    costs: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks: Mapped[str | None] = mapped_column(Text, nullable=True)
    reversibility: Mapped[str | None] = mapped_column(String(24), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    decision: Mapped[Decision] = relationship(back_populates="options", foreign_keys=[decision_id])


class DecisionCriterion(Base):
    """One evaluation criterion with a 1-5 "importance" weight — an
    explicit, small, documented scale, never an unbounded float, so a
    weight can never imply more precision than a human actually
    intended."""

    __tablename__ = "decision_criteria"
    __table_args__ = (
        CheckConstraint(
            f"weight >= {DECISION_CRITERION_WEIGHT_MIN} AND weight <= {DECISION_CRITERION_WEIGHT_MAX}",
            name="ck_decision_criteria_weight_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    decision: Mapped[Decision] = relationship(back_populates="criteria")


class DecisionAssessment(Base):
    """One option x criterion score — `score IS NULL` is the explicit,
    first-class "unknown / not assessed" state (never defaulted to 0 or a
    midpoint), so a missing assessment is always visibly missing, never
    silently counted as a bad or neutral score."""

    __tablename__ = "decision_assessments"
    __table_args__ = (
        CheckConstraint(
            f"score IS NULL OR (score >= {DECISION_ASSESSMENT_SCORE_MIN} AND score <= {DECISION_ASSESSMENT_SCORE_MAX})",
            name="ck_decision_assessments_score_range",
        ),
        UniqueConstraint("option_id", "criterion_id", name="uq_decision_assessments_option_criterion"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    option_id: Mapped[str] = mapped_column(String(36), ForeignKey("decision_options.id"), nullable=False)
    criterion_id: Mapped[str] = mapped_column(String(36), ForeignKey("decision_criteria.id"), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DecisionEvidenceLink(Base):
    """One piece of evidence linked to a decision (optionally to one
    specific option) — a typed pointer, never a copy of live content,
    exactly mirroring `app.models_research.ResearchEvidence`.
    `research_evidence_id` is provenance-only (set when this link was
    imported from a linked Research workspace's own evidence) and is
    never required — a decision may also cite a Recall source directly.
    `source_type` includes 'decision' (a decision may cite another
    decision as evidence) — one more value than
    `research_evidence.source_type`'s own frozen migration-0017
    constraint supports; see the module docstring."""

    __tablename__ = "decision_evidence_links"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN {DECISION_EVIDENCE_SOURCE_TYPES}", name="ck_decision_evidence_links_source_type_valid"
        ),
        CheckConstraint(f"stance IN {DECISION_EVIDENCE_STANCES}", name="ck_decision_evidence_links_stance_valid"),
        CheckConstraint(f"status IN {DECISION_EVIDENCE_STATUSES}", name="ck_decision_evidence_links_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    research_evidence_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("research_evidence.id"), nullable=True
    )
    linked_option_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("decision_options.id"), nullable=True)
    domain_slug: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at_snapshot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stance: Mapped[str] = mapped_column(String(16), nullable=False, default="supporting")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decision: Mapped[Decision] = relationship(back_populates="evidence_links")


class DecisionFactor(Base):
    """One assumption, risk, or unknown/question — `kind` distinguishes
    them within one small shared table rather than three near-identical
    ones. `status='resolved'` plus `resolution_note` is how an outcome
    review records "this assumption was correct/incorrect" or "this risk
    materialized/was avoided" — reusing this register rather than a
    second parallel structure."""

    __tablename__ = "decision_factors"
    __table_args__ = (
        CheckConstraint(f"kind IN {DECISION_FACTOR_KINDS}", name="ck_decision_factors_kind_valid"),
        CheckConstraint(f"status IN {DECISION_FACTOR_STATUSES}", name="ck_decision_factors_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    linked_option_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("decision_options.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    decision: Mapped[Decision] = relationship(back_populates="factors")


class DecisionBriefVersion(Base):
    """One immutable, versioned decision brief — either a deterministic
    comparison snapshot or a `source='model'` critique. Never itself a
    decision: see `DecisionFinalVersion` for the only table an explicit
    user decide() action ever writes to. Structurally identical to
    `app.models_research.ResearchBriefVersion` — the same versioning,
    citation-freezing, and validation-flagging pattern, reused
    deliberately rather than reinvented."""

    __tablename__ = "decision_brief_versions"
    __table_args__ = (
        CheckConstraint(f"source IN {DECISION_BRIEF_SOURCES}", name="ck_decision_brief_versions_source_valid"),
        CheckConstraint(f"status IN {DECISION_BRIEF_STATUSES}", name="ck_decision_brief_versions_status_valid"),
        UniqueConstraint("decision_id", "version_number", name="uq_decision_brief_versions_decision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ok")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sections_json: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    model_meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    decision: Mapped[Decision] = relationship(back_populates="brief_versions")


class DecisionFinalVersion(Base):
    """The only table an explicit `decide()` user action ever creates a
    row in — "a recommendation is not a decision." Immutable once
    created; reopening+re-deciding creates a NEW version (version_number
    increments per decision) rather than overwriting this one, so a
    historical decision and exactly why it was made stay inspectable
    forever."""

    __tablename__ = "decision_final_versions"
    __table_args__ = (
        CheckConstraint(
            "decision_confidence >= 1 AND decision_confidence <= 5",
            name="ck_decision_final_versions_confidence_range",
        ),
        UniqueConstraint("decision_id", "version_number", name="uq_decision_final_versions_decision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_option_id: Mapped[str] = mapped_column(String(36), ForeignKey("decision_options.id"), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decision_confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    decision: Mapped[Decision] = relationship(back_populates="final_versions")


class DecisionOutcomeReview(Base):
    """A later review of one specific decided version's real-world
    outcome. Never mutates `DecisionFinalVersion` or any earlier
    reasoning — this is a separate, additive record, exactly like
    `app.models_briefing`'s acknowledge/snooze rows never mutate the
    source they refer to."""

    __tablename__ = "decision_outcome_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    decision_id: Mapped[str] = mapped_column(String(36), ForeignKey("decisions.id"), nullable=False, index=True)
    decision_final_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("decision_final_versions.id"), nullable=False
    )
    what_happened: Mapped[str] = mapped_column(Text, nullable=False)
    intended_outcome_achieved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence_was_appropriate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    would_decide_same_again: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    lessons_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
