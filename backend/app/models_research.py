"""Research workspace tables. A workspace collects evidence the user picked
(typed pointers to real Recall sources, never copies), classifies it, and
produces versioned, cited briefs from only that evidence.

Each evidence row freezes a small display snapshot (title, snippet,
domain, date) so old briefs stay readable if the source changes. The
domain is always resolved server-side, since the MIND/PEOPLE boundary
depends on it, and availability is re-checked at read time rather than
stored.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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

RESEARCH_WORKSPACE_STATUSES = ("active", "archived")

# Every source type Recall itself knows how to resolve. Evidence may
# reference any of them, including document_chunk (an imported-document
# passage). Kept in sync with app.recall_service.ALL_RECALL_SOURCE_TYPES;
# a mismatch there is a real defect (see the assertion in
# app/schemas_research.py, mirroring schemas_recall.py's own pattern).
RESEARCH_EVIDENCE_SOURCE_TYPES = (
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
)

RESEARCH_EVIDENCE_CLASSIFICATIONS = ("supporting", "contradicting", "contextual", "unresolved")
RESEARCH_EVIDENCE_STATUSES = ("active", "removed")
RESEARCH_NOTE_STATUSES = ("active", "archived")
RESEARCH_BRIEF_SOURCES = ("deterministic", "model")
RESEARCH_BRIEF_STATUSES = ("ok", "invalid_citations")


class ResearchWorkspace(Base):
    """One research workspace: a question/topic plus an explicit,
    never-silently-widened domain policy governing which domains evidence
    may be drawn from. `included_domain_slugs_json` mirrors
    `app.recall_service.DEFAULT_DOMAIN_SLUGS` when unset at creation
    (LIFE/PATH/BUILD). An explicit empty list is honored literally, and
    BODY/MIND/PEOPLE only ever appear here because Bernardo explicitly
    named them, exactly like Recall's own structural privacy rule."""

    __tablename__ = "research_workspaces"
    __table_args__ = (
        CheckConstraint(f"status IN {RESEARCH_WORKSPACE_STATUSES}", name="ck_research_workspaces_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("domains.id"), nullable=True)
    included_domain_slugs_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence: Mapped[list[ResearchEvidence]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    notes: Mapped[list[ResearchNote]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    brief_versions: Mapped[list[ResearchBriefVersion]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class ResearchEvidence(Base):
    """One piece of evidence: a typed pointer to a real, already-existing
    Recall-eligible source (never a copy of its live content). `status`
    tracks removal from the workspace's own presentation (never deletes or
    alters the underlying source); a partial unique index (migration 0017)
    on (workspace_id, source_type, source_id) WHERE status='active' is what
    makes adding the same evidence twice idempotent even under a race;
    the service layer's own check-then-insert is only the first line of
    defense."""

    __tablename__ = "research_evidence"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN {RESEARCH_EVIDENCE_SOURCE_TYPES}", name="ck_research_evidence_source_type_valid"
        ),
        CheckConstraint(
            f"classification IN {RESEARCH_EVIDENCE_CLASSIFICATIONS}",
            name="ck_research_evidence_classification_valid",
        ),
        CheckConstraint(f"status IN {RESEARCH_EVIDENCE_STATUSES}", name="ck_research_evidence_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_workspaces.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    domain_slug: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    snippet_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at_snapshot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[ResearchWorkspace] = relationship(back_populates="evidence")


class ResearchNote(Base):
    """A user-authored note or provisional claim. Jarvis never generates
    or infers the content of one of these. `linked_evidence_ids_json` is a
    purely descriptive, optional cross-reference to evidence rows in the
    same workspace (never a citation-validity requirement itself; see
    app/research_service.py). Archiving (never hard-deleting) preserves
    Bernardo's own written work, mirroring the briefing and Mission Focus retention
    pattern for acknowledge/snooze/unpin."""

    __tablename__ = "research_notes"
    __table_args__ = (CheckConstraint(f"status IN {RESEARCH_NOTE_STATUSES}", name="ck_research_notes_status_valid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_workspaces.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    linked_evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workspace: Mapped[ResearchWorkspace] = relationship(back_populates="notes")


class ResearchBriefVersion(Base):
    """One immutable research brief version. Regenerating always adds a new
    version (unique per workspace, migration 0017) instead of overwriting,
    so every past brief and its citations stay inspectable. Model-written
    rows carry `model_meta_json` and are always labeled as a Jarvis draft.
    `citations_json` freezes each citation's display snapshot; availability
    is re-checked on read."""

    __tablename__ = "research_brief_versions"
    __table_args__ = (
        CheckConstraint(f"source IN {RESEARCH_BRIEF_SOURCES}", name="ck_research_brief_versions_source_valid"),
        CheckConstraint(f"status IN {RESEARCH_BRIEF_STATUSES}", name="ck_research_brief_versions_status_valid"),
        UniqueConstraint("workspace_id", "version_number", name="uq_research_brief_versions_workspace_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_workspaces.id"), nullable=False, index=True
    )
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

    workspace: Mapped[ResearchWorkspace] = relationship(back_populates="brief_versions")
