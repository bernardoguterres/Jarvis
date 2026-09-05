"""Phase 12C: request/response models for Mission Focus. Never includes a
credential, a raw token, or provider payload data — only already-
normalized, typed pin metadata and resolved display fields."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models_mission_focus import MISSION_FOCUS_SOURCE_TYPES

MissionFocusSourceType = Literal["life_task", "path_deadline", "build_checkpoint", "calendar_event", "action_proposal"]
assert set(MissionFocusSourceType.__args__) == set(MISSION_FOCUS_SOURCE_TYPES)


class MissionFocusPinCreateRequest(BaseModel):
    source_type: MissionFocusSourceType
    source_id: str = Field(min_length=1, max_length=36)
    next_action: str = Field(min_length=1, max_length=300)
    target_at: datetime | None = None
    blocker: str | None = Field(default=None, max_length=300)
    # Omit to auto-assign the next free slot (1-5) — never required from
    # the client.
    rank: int | None = Field(default=None, ge=1, le=5)


class MissionFocusPinUpdateRequest(BaseModel):
    """Edits Mission Focus's own metadata only — never the underlying
    source."""

    next_action: str = Field(min_length=1, max_length=300)
    target_at: datetime | None = None
    blocker: str | None = Field(default=None, max_length=300)


class MissionFocusReorderRequest(BaseModel):
    pin_ids: list[str] = Field(min_length=1, max_length=5)


class MissionFocusPinRead(BaseModel):
    id: str
    source_type: str
    source_id: str
    domain_slug: str | None
    rank: int
    next_action: str
    target_at: datetime | None
    blocker: str | None
    status: str
    pinned_at: datetime
    unpinned_at: datetime | None
    # Live, resolved-at-read-time display fields — never stored verbatim
    # beyond the frozen `source_title_snapshot` fallback.
    title: str
    subtitle: str | None
    link_target: str | None
    available: bool
    resolved: bool
    change_state: str | None


class MissionFocusStateRead(BaseModel):
    active_pins: list[MissionFocusPinRead]
    max_active_pins: int
    default_visible: int
