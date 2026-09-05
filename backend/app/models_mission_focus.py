"""Phase 12C: Mission Focus — a small, deliberate, Bernardo-owned watchlist
of at most five pinned items, each a typed reference to a real existing
source (never a copy of it, never a second independent task system).

Jarvis never pins, unpins, reorders, or edits anything here on its own —
every mutation is a direct, explicit user-interface action (CLAUDE.md §12
"Read"-tier presentation state, not a Phase 8 external-action proposal,
since nothing here ever touches Calendar, memory, Health, or any other
external source). See app/mission_focus_service.py for the logic that
reads/writes this table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import _new_uuid, _utcnow

# The only sources Mission Focus may reference — deliberately narrow
# (CLAUDE.md's "do not support arbitrary free-form source types"). Each
# maps to a real, already-existing typed model:
#   life_task / path_deadline / build_checkpoint -> StructuredRecord
#   calendar_event                                -> CalendarEventCache
#   action_proposal                                -> ActionProposal
MISSION_FOCUS_SOURCE_TYPES = ("life_task", "path_deadline", "build_checkpoint", "calendar_event", "action_proposal")

MISSION_FOCUS_PIN_STATUSES = ("active", "unpinned")

MISSION_FOCUS_MAX_ACTIVE_PINS = 5
MISSION_FOCUS_DEFAULT_VISIBLE = 3


class MissionFocusPin(Base):
    """One pinned reference. `source_type`/`source_id` are a typed pointer
    to the real source row — never a copy of its content. `domain_slug` is
    always resolved and stored server-side from the actual source at pin
    time (never accepted from the client), since it is the field the
    MIND/PEOPLE privacy boundary depends on. `rank` (1-5) is Bernardo's own
    explicit ordering; `next_action` is his own written text — Jarvis never
    generates or infers it. `source_fingerprint_at_pin` records the
    source's own content fingerprint (the same function `briefing_service`
    uses) at the moment of pinning, for lineage/audit only — it does not
    drive suppression the way Phase 12B's acknowledge/snooze fingerprints
    do. Unpinning sets `status='unpinned'` and `unpinned_at` — the row is
    never deleted, matching Phase 12B's acknowledge/snooze retention
    pattern, and never deletes or alters the underlying source."""

    # Two partial unique indexes (declared in the migration, not here, since
    # SQLAlchemy's declarative UniqueConstraint has no WHERE clause) are
    # what actually prevent two simultaneously-*active* pins for the same
    # source, and two *active* pins sharing a rank — enforced by the
    # database itself: `uq_mission_focus_active_source` on
    # (source_type, source_id) WHERE status='active', and
    # `uq_mission_focus_active_rank` on (rank) WHERE status='active'. A
    # plain (non-partial) unique constraint here would wrongly forbid ever
    # re-pinning the same source a second time after a prior unpin, since
    # both 'unpinned' rows would collide.
    # `rank`'s CHECK only enforces `>= 1` at the database level, not the
    # full 1-5 display range — reordering (`mission_focus_service.
    # reorder_pins`) needs brief, safely-out-of-the-way temporary rank
    # values (>=100) while permuting the active set, to avoid transiently
    # colliding with `uq_mission_focus_active_rank` on the SAME 5 rows
    # (SQLite has no deferrable UNIQUE constraint to lean on instead). Any
    # rank actually meant to represent Bernardo's real 1-5 ordering is
    # strictly validated at the one or two service-layer call sites that
    # ever set one (`create_pin`'s explicit `rank` argument, and
    # `reorder_pins`'s final assignment loop) — never trusted from a
    # request body without that check.
    __tablename__ = "mission_focus_pins"
    __table_args__ = (
        CheckConstraint(f"source_type IN {MISSION_FOCUS_SOURCE_TYPES}", name="ck_mission_focus_pins_source_type_valid"),
        CheckConstraint(f"status IN {MISSION_FOCUS_PIN_STATUSES}", name="ck_mission_focus_pins_status_valid"),
        CheckConstraint("rank >= 1", name="ck_mission_focus_pins_rank_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    domain_slug: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # A frozen display-text snapshot taken at pin time (same rationale as
    # Phase 12B's acknowledge/snooze `title_snapshot`) — lets a truly
    # vanished source (e.g. a Calendar event rolled out of the sync
    # window) still be shown with a real, truthful last-known title
    # instead of a bare "unavailable."
    source_title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    next_action: Mapped[str] = mapped_column(String(300), nullable=False)
    target_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocker: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source_fingerprint_at_pin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    unpinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
