"""SQLAlchemy ORM models for Phase 1: Domain, Conversation, Message."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid.uuid4())


VALID_ROLES = ("user", "assistant", "system")

# Fixed UUIDs for the six seeded domains so reinstalling or reseeding never
# produces new identities.
DOMAIN_SEEDS = [
    {
        "id": "11111111-1111-4111-8111-111111111111",
        "slug": "body",
        "name": "BODY",
        "description": "Fitness, physical health, weight, strength, training, knee symptoms, sleep, nutrition, recovery, wearable data and medical preparation.",
    },
    {
        "id": "22222222-2222-4222-8222-222222222222",
        "slug": "mind",
        "name": "MIND",
        "description": "Mood, anxiety, habits, confidence, motivation, journaling, emotional check-ins, reflection and personal patterns.",
    },
    {
        "id": "33333333-3333-4333-8333-333333333333",
        "slug": "people",
        "name": "PEOPLE",
        "description": "Romantic relationship, family, friendships, social plans, important interactions, communication and interpersonal boundaries.",
    },
    {
        "id": "44444444-4444-4444-8444-444444444444",
        "slug": "path",
        "name": "PATH",
        "description": "UCL, education, career direction, employment, applications, interviews, skills, deadlines and long-term goals.",
    },
    {
        "id": "55555555-5555-4555-8555-555555555555",
        "slug": "build",
        "name": "BUILD",
        "description": "Software projects, Alpha projects, transaction foundation-model work, business ideas, coding, research, project decisions, versions and next actions.",
    },
    {
        "id": "66666666-6666-4666-8666-666666666666",
        "slug": "life",
        "name": "LIFE",
        "description": "Calendar, reminders, finances, housing, travel, purchases, administration and general planning.",
    },
]


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="domain", cascade="all, delete-orphan"
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    # NULL means a general Jarvis conversation — not a seventh domain, just
    # the absence of one. See docs/DECISIONS.md and migration 0011.
    domain_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    domain: Mapped["Domain | None"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(f"role IN {VALID_ROLES}", name="ck_messages_role_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


AGENT_RUN_STATUSES = ("pending", "running", "succeeded", "failed", "cancelled")


class AgentRun(Base):
    """Audit record for one attempt to send a conversation turn to an agent
    provider (Hermes). Kept separate from Message so transient run state
    (status, latency, token usage, provider error) never overloads the
    message table itself.
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {AGENT_RUN_STATUSES}", name="ck_agent_runs_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(nullable=True)
    external_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    conversation: Mapped["Conversation"] = relationship()
    context_snapshot: Mapped["ContextSnapshot | None"] = relationship(
        back_populates="agent_run", uselist=False
    )
