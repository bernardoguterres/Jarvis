"""Phase 4: model-independent local memory, structured records, domain
summaries, and auditable context snapshots.

The Jarvis Controller's SQLite database (these tables) is the only
authoritative personal-memory system — see CLAUDE.md §7 and
docs/ARCHITECTURE.md. Nothing here depends on which reasoning model or
agent harness is active.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import AgentRun, _new_uuid, _utcnow  # noqa: F401  (AgentRun used by relationship string ref)

MEMORY_SCOPES = ("global", "domain")
MEMORY_KINDS = (
    "identity",
    "preference",
    "fact",
    "goal",
    "constraint",
    "decision",
    "health_context",
    "relationship_context",
)
MEMORY_STATUSES = ("active", "archived", "deleted")
SENSITIVITY_LEVELS = ("normal", "sensitive")

STRUCTURED_RECORD_TYPES = (
    "body_weight",
    "body_symptom",
    "mind_checkin",
    "people_interaction",
    "path_deadline",
    "build_checkpoint",
    "life_task",
)


class MemoryItem(Base):
    """A stable logical memory. Mutable fields here mirror the CURRENT
    version for convenient querying; the authoritative history lives in
    MemoryVersion rows, which are never overwritten."""

    __tablename__ = "memory_items"
    __table_args__ = (
        CheckConstraint(f"scope IN {MEMORY_SCOPES}", name="ck_memory_items_scope_valid"),
        CheckConstraint(f"kind IN {MEMORY_KINDS}", name="ck_memory_items_kind_valid"),
        CheckConstraint(f"status IN {MEMORY_STATUSES}", name="ck_memory_items_status_valid"),
        CheckConstraint(
            f"sensitivity IN {SENSITIVITY_LEVELS}", name="ck_memory_items_sensitivity_valid"
        ),
        CheckConstraint(
            "(scope = 'global' AND domain_id IS NULL) OR (scope = 'domain' AND domain_id IS NOT NULL)",
            name="ck_memory_items_scope_domain_consistency",
        ),
        CheckConstraint("importance >= 1 AND importance <= 5", name="ck_memory_items_importance_range"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="ck_memory_items_confidence_range"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    importance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    source_conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    source_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    current_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("memory_versions.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )

    versions: Mapped[list["MemoryVersion"]] = relationship(
        back_populates="memory_item",
        cascade="all, delete-orphan",
        order_by="MemoryVersion.version_number",
        foreign_keys="MemoryVersion.memory_item_id",
    )
    current_version: Mapped["MemoryVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class MemoryVersion(Base):
    """Immutable content snapshot of a MemoryItem. Never updated in place."""

    __tablename__ = "memory_versions"
    __table_args__ = (
        UniqueConstraint("memory_item_id", "version_number", name="uq_memory_versions_item_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    memory_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    memory_item: Mapped["MemoryItem"] = relationship(
        back_populates="versions", foreign_keys=[memory_item_id]
    )


class DomainSummary(Base):
    """One current-summary slot per domain; full history in DomainSummaryVersion."""

    __tablename__ = "domain_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    domain_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    current_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domain_summary_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    versions: Mapped[list["DomainSummaryVersion"]] = relationship(
        back_populates="domain_summary",
        cascade="all, delete-orphan",
        order_by="DomainSummaryVersion.version_number",
        foreign_keys="DomainSummaryVersion.domain_summary_id",
    )
    current_version: Mapped["DomainSummaryVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class DomainSummaryVersion(Base):
    __tablename__ = "domain_summary_versions"
    __table_args__ = (
        UniqueConstraint(
            "domain_summary_id", "version_number", name="uq_domain_summary_versions_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    domain_summary_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("domain_summaries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    domain_summary: Mapped["DomainSummary"] = relationship(
        back_populates="versions", foreign_keys=[domain_summary_id]
    )


class StructuredRecord(Base):
    __tablename__ = "structured_records"
    __table_args__ = (
        CheckConstraint(
            f"record_type IN {STRUCTURED_RECORD_TYPES}", name="ck_structured_records_type_valid"
        ),
        CheckConstraint(
            f"sensitivity IN {SENSITIVITY_LEVELS}", name="ck_structured_records_sensitivity_valid"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    domain_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContextSnapshot(Base):
    """Auditable record of exactly what local data was assembled into a
    turn's context. Not model reasoning — a source audit only."""

    __tablename__ = "context_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    agent_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # NULL for a general-conversation turn — no domain was active. See
    # migration 0011.
    active_domain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=True
    )
    additional_domain_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    global_memory_version_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    domain_memory_version_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    domain_summary_version_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    structured_record_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    recent_message_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    retrieval_query: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retrieval_reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    estimated_context_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document_chunk_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    calendar_event_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    google_health_summary_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    agent_run: Mapped["AgentRun"] = relationship(back_populates="context_snapshot")
