"""Phase 12A: persisted privacy settings for the on-demand Home
situational briefing (see app/briefing_service.py).

A single-row table — analogous in spirit to app/models_routines.py's
RoutineSchedule, but simpler (no schedule/enable state, since the Home
briefing is always assembled on demand, never run in the background).
Only a per-sensitive-domain opt-in flag is stored; nothing here is a
credential or personal content, just a boolean preference.

Defaults match Bernardo's already-recorded Phase 10B privacy selection
(CLAUDE.md, docs/ROADMAP.md): BODY included, MIND and PEOPLE excluded.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import _new_uuid, _utcnow

BRIEFING_SETTINGS_SINGLETON_ID = "singleton"

# --- Phase 12B: briefing continuity (snapshots, per-identity ledger, ------
# acknowledgements, snoozes). See app/briefing_service.py for the logic
# that reads/writes these tables — nothing here is written to by anything
# other than that module (and, for BriefingSnapshot only, the Phase 10B
# Morning Briefing routine's own lightweight audit row — never the ledger
# or ack/snooze tables, which are exclusively a Home-briefing concern).

BRIEFING_SNAPSHOT_CONSUMERS = ("home", "morning_briefing")
BRIEFING_SNAPSHOT_TRIGGERS = (
    "home_view",
    "home_refresh",
    "morning_briefing_manual",
    "morning_briefing_scheduled",
    "morning_briefing_startup_catchup",
)
BRIEFING_ITEM_STATUSES = ("active", "resolved")
BRIEFING_ACK_STATUSES = ("active", "restored")
BRIEFING_SNOOZE_STATUSES = ("active", "expired", "restored")
BRIEFING_SNOOZE_DURATIONS = ("1h", "4h", "tomorrow_morning", "1w")


class BriefingSnapshot(Base):
    """One row per candidate-set comparison pass — an audit/history trail
    and the spam-prevention dedup anchor (see
    `briefing_service.record_snapshot`). `consumer` is the baseline
    lineage ('home' vs 'morning_briefing') that `BriefingItemState` change
    detection is scoped to; `trigger` is a finer-grained audit label that
    never affects comparison logic. `content_digest` is a stable hash of
    the full candidate set's (stable_key, fingerprint) pairs (Home) or of
    the routine's own rendered output (Morning Briefing) — never raw
    provider payloads or secrets."""

    __tablename__ = "briefing_snapshots"
    __table_args__ = (
        CheckConstraint(f"consumer IN {BRIEFING_SNAPSHOT_CONSUMERS}", name="ck_briefing_snapshots_consumer_valid"),
        CheckConstraint(f"trigger IN {BRIEFING_SNAPSHOT_TRIGGERS}", name="ck_briefing_snapshots_trigger_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    consumer: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_digest: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BriefingItemState(Base):
    """The Home-briefing continuity ledger — one row per stable identity
    ever seen by the Home assembler (across all its candidate-generating
    functions), independent of any single snapshot. This is what
    `new`/`changed`/`ongoing`/`resolved`/`reopened` classification is
    computed against; the Morning Briefing routine never reads or writes
    this table. `last_title`/`last_subtitle`/`last_category`/
    `last_link_target` cache the most recent active display text so a
    freshly-resolved item can still be shown with a real, truthful label
    on the one pass where its resolution is reported."""

    __tablename__ = "briefing_item_states"
    __table_args__ = (
        UniqueConstraint("stable_key", name="uq_briefing_item_states_stable_key"),
        CheckConstraint(f"status IN {BRIEFING_ITEM_STATUSES}", name="ck_briefing_item_states_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    domain_slug: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    current_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    last_subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_category: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_link_target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class BriefingAcknowledgement(Base):
    """A local presentation preference, never a mutation of the
    underlying source (CLAUDE.md, Phase 12B). Suppresses one exact
    (stable_key, fingerprint) pair from the main briefing until the
    fingerprint changes or the item is explicitly restored. `*_snapshot`
    columns freeze the display text at acknowledge time so the compact
    "Acknowledged" history view never needs to re-derive from a possibly
    already-resolved candidate."""

    __tablename__ = "briefing_acknowledgements"
    __table_args__ = (
        CheckConstraint(f"status IN {BRIEFING_ACK_STATUSES}", name="ck_briefing_acknowledgements_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    subtitle_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain_slug_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    link_target_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BriefingSnooze(Base):
    """Same shape/rationale as `BriefingAcknowledgement`, but time-bounded
    (`snooze_until`) rather than indefinite, and drawn from a small
    server-validated `duration_key` enum rather than an arbitrary
    client-supplied timestamp (CLAUDE.md §12 — never trust an unbounded
    client payload for something that affects what's shown). Never
    executes or schedules any external action; purely a local suppression
    window."""

    __tablename__ = "briefing_snoozes"
    __table_args__ = (
        CheckConstraint(f"status IN {BRIEFING_SNOOZE_STATUSES}", name="ck_briefing_snoozes_status_valid"),
        CheckConstraint(f"duration_key IN {BRIEFING_SNOOZE_DURATIONS}", name="ck_briefing_snoozes_duration_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    stable_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    duration_key: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    subtitle_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    domain_slug_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    link_target_snapshot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snoozed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    snooze_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class BriefingSettings(Base):
    """One fixed row. `include_body`/`include_mind`/`include_people` gate
    whether that sensitive domain's data may ever be considered by
    app/briefing_service.py's Home briefing assembler — never a default,
    always an explicit, persisted, restart-surviving choice."""

    __tablename__ = "briefing_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default=BRIEFING_SETTINGS_SINGLETON_ID)
    include_body: Mapped[bool] = mapped_column(nullable=False, default=True)
    include_mind: Mapped[bool] = mapped_column(nullable=False, default=False)
    include_people: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
