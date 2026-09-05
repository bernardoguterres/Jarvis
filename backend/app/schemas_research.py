"""Phase 12E: Source-Grounded Research Workspace — request/response models.
Never includes a raw provider payload, credential, or unescaped client-
supplied text presented as an authoritative source snapshot — every
title/snippet field here was resolved server-side (see
app.research_service)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models_research import (
    RESEARCH_BRIEF_SOURCES,
    RESEARCH_BRIEF_STATUSES,
    RESEARCH_EVIDENCE_CLASSIFICATIONS,
    RESEARCH_EVIDENCE_SOURCE_TYPES,
    RESEARCH_WORKSPACE_STATUSES,
)
from app.recall_service import ALL_RECALL_SOURCE_TYPES

ResearchSourceType = Literal[
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
]
# Evidence may reference this fixed, already-shipped subset of Recall's
# own source vocabulary — a mismatch against RESEARCH_EVIDENCE_SOURCE_TYPES
# (which mirrors research_evidence's own frozen migration-0017 CHECK
# constraint) is a real defect, not a config typo. This is deliberately a
# SUBSET assertion, not equality: Phase 12F added "decision" to
# app.recall_service.ALL_RECALL_SOURCE_TYPES (a decision may cite another
# decision as evidence, via its own decision_evidence_links table), but
# research_evidence's CHECK constraint predates Decisions and — per
# CLAUDE.md — an already-shipped migration is never edited to add it
# retroactively. A Decision may still cite a Research workspace's evidence
# (via decision_evidence_links.research_evidence_id provenance); the
# reverse (citing a Decision as Research evidence) is simply not
# supported, which was never a product requirement.
assert set(ResearchSourceType.__args__) == set(RESEARCH_EVIDENCE_SOURCE_TYPES) <= set(ALL_RECALL_SOURCE_TYPES)

ResearchDomainSlug = Literal["body", "build", "life", "mind", "path", "people"]
ResearchWorkspaceStatus = Literal["active", "archived"]
assert set(ResearchWorkspaceStatus.__args__) == set(RESEARCH_WORKSPACE_STATUSES)
ResearchEvidenceClassification = Literal["supporting", "contradicting", "contextual", "unresolved"]
assert set(ResearchEvidenceClassification.__args__) == set(RESEARCH_EVIDENCE_CLASSIFICATIONS)
ResearchBriefSource = Literal["deterministic", "model"]
assert set(ResearchBriefSource.__args__) == set(RESEARCH_BRIEF_SOURCES)
ResearchBriefStatus = Literal["ok", "invalid_citations"]
assert set(ResearchBriefStatus.__args__) == set(RESEARCH_BRIEF_STATUSES)


class ResearchWorkspaceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    domain_slug: ResearchDomainSlug | None = None
    # None -> the default LIFE/PATH/BUILD policy; an explicit (possibly
    # empty) list is honored literally — never silently widened. Naming a
    # sensitive domain here is Bernardo's own explicit choice at creation
    # time, exactly like Recall's own `domains` search parameter.
    included_domain_slugs: list[ResearchDomainSlug] | None = None


class ResearchWorkspaceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    # Sentinel-free: omitting the field entirely leaves the current policy
    # untouched; an explicit (possibly empty) list replaces it outright.
    # FastAPI/Pydantic distinguishes "field absent" from "field null" via
    # `exclude_unset` at the router, not by a magic value here.
    included_domain_slugs: list[ResearchDomainSlug] | None = None


class ResearchWorkspaceRead(BaseModel):
    id: str
    title: str
    domain_slug: ResearchDomainSlug | None
    included_domain_slugs: list[str]
    status: ResearchWorkspaceStatus
    evidence_count: int
    note_count: int
    latest_brief_version: int | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class ResearchEvidenceAdd(BaseModel):
    source_type: ResearchSourceType
    source_id: str = Field(min_length=1, max_length=36)
    classification: ResearchEvidenceClassification = "unresolved"
    note: str | None = Field(default=None, max_length=2000)


class ResearchEvidenceUpdate(BaseModel):
    classification: ResearchEvidenceClassification | None = None
    note: str | None = Field(default=None, max_length=2000)


class ResearchEvidenceRead(BaseModel):
    id: str
    workspace_id: str
    source_type: ResearchSourceType
    source_id: str
    domain_slug: ResearchDomainSlug | None
    title_snapshot: str
    snippet_snapshot: str
    occurred_at_snapshot: str | None
    classification: ResearchEvidenceClassification
    note: str | None
    status: Literal["active", "removed"]
    available: bool
    unavailable_reason: str | None
    link_target: str | None
    added_at: datetime
    updated_at: datetime


class ResearchNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    linked_evidence_ids: list[str] = Field(default_factory=list)


class ResearchNoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    linked_evidence_ids: list[str] = Field(default_factory=list)


class ResearchNoteRead(BaseModel):
    id: str
    workspace_id: str
    content: str
    linked_evidence_ids: list[str]
    status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime


class ResearchCitationRead(BaseModel):
    number: int
    evidence_id: str
    source_type: ResearchSourceType
    source_id: str
    domain_slug: ResearchDomainSlug | None
    title_snapshot: str
    snippet_snapshot: str
    available: bool
    unavailable_reason: str | None
    link_target: str | None


class ResearchModelMetaRead(BaseModel):
    provider: str
    model: str
    latency_ms: int
    evidence_ids_used: list[str]


class ResearchBriefVersionRead(BaseModel):
    id: str
    workspace_id: str
    version_number: int
    source: ResearchBriefSource
    status: ResearchBriefStatus
    title: str
    sections_json: str
    citations: list[ResearchCitationRead]
    validation_issues: list[str]
    model_meta: ResearchModelMetaRead | None
    generated_at: datetime
    created_at: datetime


class ResearchBriefVersionSummary(BaseModel):
    id: str
    version_number: int
    source: ResearchBriefSource
    status: ResearchBriefStatus
    generated_at: datetime
