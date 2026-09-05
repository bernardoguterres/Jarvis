"""Phase 8: controller-owned permissions, an auditable action lifecycle,
lifecycle hooks, and a local versioned skill system.

Nothing here lets Hermes or any model call these tables directly — Hermes's
own toolsets remain fully disabled (see docs/ARCHITECTURE.md §8c). Every
mutation Jarvis itself proposes must pass through ActionProposal's
propose -> approve -> execute lifecycle in app/action_service.py; there is
no path from model-generated text to execution (CLAUDE.md §12, D9x below).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import _new_uuid, _utcnow

# Fixed, code-owned capability allowlist — never user- or model-extensible.
# Every capability here only ever proposes a controller-owned internal
# record; none has an external side effect (CLAUDE.md §12 "Confirm" tier).
CAPABILITY_IDS = (
    "memory.create",
    "structured_record.create",
    "domain_summary.update",
    "google_calendar.event.create",
    "google_calendar.event.update",
    "google_calendar.event.delete",
)

PERMISSION_LEVELS = ("read", "draft", "confirm", "execute")

ACTION_STATUSES = (
    "proposed",
    "approved",
    "denied",
    "expired",
    "executing",
    "succeeded",
    "failed",
)

HOOK_PHASES = ("before_context", "before_action", "after_action", "on_failure")
HOOK_OUTCOMES = ("ok", "blocked", "error")

SKILL_STATUSES = ("draft", "active", "archived")
SKILL_CREATORS = ("user", "jarvis")


class ActionProposal(Base):
    """One proposed Jarvis-initiated mutation and its full lifecycle state.

    `arguments_json`, `capability_id`, and `domain_id` are immutable after
    creation — `payload_digest` is computed once from exactly those fields
    and never recomputed, so approval can be bound to "the exact proposed
    action" (CLAUDE.md §12) rather than to a mutable row.
    """

    __tablename__ = "action_proposals"
    __table_args__ = (
        CheckConstraint(f"capability_id IN {CAPABILITY_IDS}", name="ck_action_proposals_capability_valid"),
        CheckConstraint(
            f"permission_level IN {PERMISSION_LEVELS}", name="ck_action_proposals_permission_valid"
        ),
        CheckConstraint(f"status IN {ACTION_STATUSES}", name="ck_action_proposals_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    capability_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True, index=True
    )
    permission_level: Mapped[str] = mapped_column(String(16), nullable=False, default="confirm")
    arguments_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed", index=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="manual_proposal")

    confirmation_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    audit_events: Mapped[list["ActionAuditEvent"]] = relationship(
        back_populates="action_proposal", cascade="all, delete-orphan", order_by="ActionAuditEvent.created_at"
    )


class ActionAuditEvent(Base):
    """Append-only lifecycle audit trail for one ActionProposal. Never
    updated or deleted once written — mirrors MemoryVersion's
    immutable-history pattern."""

    __tablename__ = "action_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    action_proposal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("action_proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    action_proposal: Mapped["ActionProposal"] = relationship(back_populates="audit_events")


class HookEvent(Base):
    """Auditable outcome of one registered lifecycle hook invocation."""

    __tablename__ = "hook_events"
    __table_args__ = (
        CheckConstraint(f"phase IN {HOOK_PHASES}", name="ck_hook_events_phase_valid"),
        CheckConstraint(f"outcome IN {HOOK_OUTCOMES}", name="ck_hook_events_outcome_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    hook_name: Mapped[str] = mapped_column(String(128), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    action_proposal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("action_proposals.id", ondelete="SET NULL"), nullable=True, index=True
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Skill(Base):
    """A reusable declarative workflow. Mutable fields mirror the current
    version; full history lives in SkillVersion (never overwritten)."""

    __tablename__ = "skills"
    __table_args__ = (
        CheckConstraint(f"status IN {SKILL_STATUSES}", name="ck_skills_status_valid"),
        CheckConstraint(f"created_by IN {SKILL_CREATORS}", name="ck_skills_created_by_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    domain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invocation_phrases_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    current_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True
    )

    versions: Mapped[list["SkillVersion"]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillVersion.version_number",
        foreign_keys="SkillVersion.skill_id",
    )
    current_version: Mapped["SkillVersion | None"] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class SkillVersion(Base):
    """Immutable content snapshot of a Skill. Never updated in place."""

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_skill_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    skill_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_steps_json: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    skill: Mapped["Skill"] = relationship(back_populates="versions", foreign_keys=[skill_id])
