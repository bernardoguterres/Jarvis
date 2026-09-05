"""Phase 12F: Evidence-Based Decision Room — request/response models.
Never includes a raw model prompt, provider metadata beyond the small
labeled summary Research's own `ResearchModelMetaRead` already
established, or unescaped client-supplied text presented as an
authoritative source snapshot — every title/snippet field here was
resolved server-side (see app.decision_service)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models_decisions import (
    DECISION_BRIEF_SOURCES,
    DECISION_BRIEF_STATUSES,
    DECISION_EVIDENCE_SOURCE_TYPES,
    DECISION_EVIDENCE_STANCES,
    DECISION_FACTOR_KINDS,
    DECISION_OPTION_STATUSES,
    DECISION_STATUSES,
    REVERSIBILITY_LEVELS,
)
from app.recall_service import ALL_RECALL_SOURCE_TYPES

DecisionSourceType = Literal[
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
]
# Unlike Research (a documented subset — see schemas_research.py's own
# comment), Decision's evidence-link table is new in this same phase, so
# it correctly covers the FULL current Recall vocabulary, "decision"
# included (a decision may cite another decision as evidence).
assert set(DecisionSourceType.__args__) == set(DECISION_EVIDENCE_SOURCE_TYPES) == set(ALL_RECALL_SOURCE_TYPES)

DecisionDomainSlug = Literal["body", "build", "life", "mind", "path", "people"]
DecisionStatus = Literal["draft", "evaluating", "decided", "reopened", "superseded", "abandoned"]
assert set(DecisionStatus.__args__) == set(DECISION_STATUSES)
DecisionReversibility = Literal["easily_reversible", "hard_to_reverse", "irreversible"]
assert set(DecisionReversibility.__args__) == set(REVERSIBILITY_LEVELS)
DecisionOptionStatus = Literal["active", "eliminated", "chosen"]
assert set(DecisionOptionStatus.__args__) == set(DECISION_OPTION_STATUSES)
DecisionEvidenceStance = Literal["supporting", "contradicting", "contextual", "unresolved"]
assert set(DecisionEvidenceStance.__args__) == set(DECISION_EVIDENCE_STANCES)
DecisionFactorKind = Literal["assumption", "risk", "unknown"]
assert set(DecisionFactorKind.__args__) == set(DECISION_FACTOR_KINDS)
DecisionFactorStatus = Literal["open", "resolved"]
DecisionBriefSource = Literal["deterministic", "model"]
assert set(DecisionBriefSource.__args__) == set(DECISION_BRIEF_SOURCES)
DecisionBriefStatus = Literal["ok", "invalid_citations"]
assert set(DecisionBriefStatus.__args__) == set(DECISION_BRIEF_STATUSES)


# --- decisions -----------------------------------------------------------------


class DecisionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    domain_slug: DecisionDomainSlug | None = None
    research_workspace_id: str | None = None
    included_domain_slugs: list[DecisionDomainSlug] | None = None


class DecisionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    included_domain_slugs: list[DecisionDomainSlug] | None = None
    review_date: datetime | None = None
    cost_of_delay_note: str | None = Field(default=None, max_length=2000)
    info_confidence: int | None = Field(default=None, ge=1, le=5)
    reversibility: DecisionReversibility | None = None


class DecisionLinkWorkspaceRequest(BaseModel):
    research_workspace_id: str | None = None


class DecideRequest(BaseModel):
    selected_option_id: str
    rationale: str = Field(min_length=1, max_length=4000)
    decision_confidence: int = Field(ge=1, le=5)


class SupersedeRequest(BaseModel):
    new_decision_id: str


class AbandonRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class DecisionRead(BaseModel):
    id: str
    title: str
    description: str | None
    domain_slug: DecisionDomainSlug | None
    research_workspace_id: str | None
    included_domain_slugs: list[str]
    effective_domain_slugs: list[str]
    status: DecisionStatus
    review_date: datetime | None
    cost_of_delay_note: str | None
    info_confidence: int | None
    reversibility: DecisionReversibility | None
    supersedes_decision_id: str | None
    superseded_by_decision_id: str | None
    abandoned_at: datetime | None
    abandoned_reason: str | None
    option_count: int
    criterion_count: int
    evidence_count: int
    latest_brief_version: int | None
    is_decided: bool
    review_due: bool
    created_at: datetime
    updated_at: datetime


# --- options ---------------------------------------------------------------------


class DecisionOptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    benefits: str | None = Field(default=None, max_length=4000)
    costs: str | None = Field(default=None, max_length=4000)
    risks: str | None = Field(default=None, max_length=4000)
    reversibility: DecisionReversibility | None = None


class DecisionOptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    benefits: str | None = Field(default=None, max_length=4000)
    costs: str | None = Field(default=None, max_length=4000)
    risks: str | None = Field(default=None, max_length=4000)
    reversibility: DecisionReversibility | None = None
    status: Literal["active", "eliminated"] | None = None


class DecisionOptionRead(BaseModel):
    id: str
    decision_id: str
    name: str
    description: str | None
    benefits: str | None
    costs: str | None
    risks: str | None
    reversibility: DecisionReversibility | None
    status: DecisionOptionStatus
    rank: int
    created_at: datetime
    updated_at: datetime


# --- criteria and assessments ---------------------------------------------------


class DecisionCriterionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    weight: int = Field(ge=1, le=5)


class DecisionCriterionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    weight: int | None = Field(default=None, ge=1, le=5)


class DecisionCriterionRead(BaseModel):
    id: str
    decision_id: str
    name: str
    description: str | None
    weight: int
    rank: int
    created_at: datetime
    updated_at: datetime


class DecisionAssessmentSet(BaseModel):
    option_id: str
    criterion_id: str
    score: int | None = Field(default=None, ge=1, le=5)
    note: str | None = Field(default=None, max_length=1000)


class DecisionAssessmentRead(BaseModel):
    id: str
    option_id: str
    criterion_id: str
    score: int | None
    note: str | None
    created_at: datetime
    updated_at: datetime


# --- score breakdown (pure, deterministic) --------------------------------------


class OptionScoreRead(BaseModel):
    option_id: str
    option_name: str
    total_score: int
    assessed_count: int
    total_criteria: int
    missing_criterion_ids: list[str]
    missing_criterion_names: list[str]


class SensitivityWarningRead(BaseModel):
    criterion_id: str
    criterion_name: str
    explanation: str


class ScoreBreakdownRead(BaseModel):
    options: list[OptionScoreRead]
    ranked_option_ids: list[str]
    tied: bool
    sensitivity_warnings: list[SensitivityWarningRead]
    incomplete: bool


# --- evidence --------------------------------------------------------------------


class DecisionEvidenceAdd(BaseModel):
    source_type: DecisionSourceType
    source_id: str = Field(min_length=1, max_length=36)
    stance: DecisionEvidenceStance = "supporting"
    note: str | None = Field(default=None, max_length=2000)
    linked_option_id: str | None = None


class DecisionEvidenceImportFromResearch(BaseModel):
    research_evidence_id: str
    stance: DecisionEvidenceStance = "supporting"
    linked_option_id: str | None = None


class DecisionEvidenceUpdate(BaseModel):
    stance: DecisionEvidenceStance | None = None
    note: str | None = Field(default=None, max_length=2000)
    linked_option_id: str | None = None


class DecisionEvidenceRead(BaseModel):
    id: str
    decision_id: str
    source_type: DecisionSourceType
    source_id: str
    research_evidence_id: str | None
    linked_option_id: str | None
    domain_slug: DecisionDomainSlug | None
    title_snapshot: str
    snippet_snapshot: str
    occurred_at_snapshot: str | None
    stance: DecisionEvidenceStance
    note: str | None
    status: Literal["active", "removed"]
    available: bool
    unavailable_reason: str | None
    link_target: str | None
    added_at: datetime
    updated_at: datetime


# --- factors: assumptions / risks / unknowns ------------------------------------


class DecisionFactorCreate(BaseModel):
    kind: DecisionFactorKind
    content: str = Field(min_length=1, max_length=2000)
    linked_option_id: str | None = None


class DecisionFactorUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    linked_option_id: str | None = None


class DecisionFactorResolve(BaseModel):
    resolution_note: str | None = Field(default=None, max_length=2000)


class DecisionFactorRead(BaseModel):
    id: str
    decision_id: str
    kind: DecisionFactorKind
    content: str
    linked_option_id: str | None
    status: DecisionFactorStatus
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --- briefs (deterministic + model critique) ------------------------------------


class DecisionCitationRead(BaseModel):
    number: int
    evidence_id: str
    source_type: DecisionSourceType
    source_id: str
    domain_slug: DecisionDomainSlug | None
    title_snapshot: str
    snippet_snapshot: str
    available: bool
    unavailable_reason: str | None
    link_target: str | None


class DecisionModelMetaRead(BaseModel):
    provider: str
    model: str
    latency_ms: int
    evidence_ids_used: list[str]


class DecisionBriefVersionRead(BaseModel):
    id: str
    decision_id: str
    version_number: int
    source: DecisionBriefSource
    status: DecisionBriefStatus
    title: str
    sections_json: str
    citations: list[DecisionCitationRead]
    validation_issues: list[str]
    model_meta: DecisionModelMetaRead | None
    generated_at: datetime
    created_at: datetime


class DecisionBriefVersionSummary(BaseModel):
    id: str
    version_number: int
    source: DecisionBriefSource
    status: DecisionBriefStatus
    generated_at: datetime


# --- final decision + outcome review ---------------------------------------------


class DecisionFinalVersionRead(BaseModel):
    id: str
    decision_id: str
    version_number: int
    selected_option_id: str
    selected_option_name: str
    rationale: str
    decision_confidence: int
    decided_at: datetime
    created_at: datetime


class DecisionOutcomeReviewCreate(BaseModel):
    decision_final_version_id: str | None = None
    what_happened: str = Field(min_length=1, max_length=4000)
    intended_outcome_achieved: bool | None = None
    confidence_was_appropriate: bool | None = None
    would_decide_same_again: bool | None = None
    lessons_learned: str | None = Field(default=None, max_length=4000)


class DecisionOutcomeReviewRead(BaseModel):
    id: str
    decision_id: str
    decision_final_version_id: str
    what_happened: str
    intended_outcome_achieved: bool | None
    confidence_was_appropriate: bool | None
    would_decide_same_again: bool | None
    lessons_learned: str | None
    reviewed_at: datetime
    created_at: datetime


class CalibrationSummaryRead(BaseModel):
    # None fields mean "not enough reviewed decisions yet" — never a
    # fabricated statistic from a tiny sample; see
    # app.decision_service.MIN_CALIBRATION_SAMPLE.
    reviewed_count: int
    minimum_sample: int
    has_enough_data: bool
    confidence_appropriate_rate: float | None
    would_decide_same_rate: float | None
    outcome_achieved_rate: float | None
