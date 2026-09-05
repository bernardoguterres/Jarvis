"""Mission Control / Current Focus — request/response models. Never
includes a credential, raw token, or provider payload — only already-
normalized, typed session/candidate fields."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models_mission_control import FOCUS_SESSION_MAX_MINUTES, FOCUS_SESSION_MIN_MINUTES, FOCUS_SESSION_SOURCE_TYPES

FocusSessionSourceType = Literal[
    "life_task", "path_deadline", "build_checkpoint", "calendar_event", "action_proposal", "manual"
]
assert set(FocusSessionSourceType.__args__) == set(FOCUS_SESSION_SOURCE_TYPES)

FocusSessionStatus = Literal["planned", "active", "paused", "completed", "abandoned"]


class MissionCandidateRead(BaseModel):
    stable_key: str
    domain_slug: str | None
    title: str
    subtitle: str | None
    reason: str
    source_type: str
    source_ids: list[str]
    freshness: str
    link_target: str | None


class MissionCandidatesRead(BaseModel):
    """`recommended`/`alternatives` are always phrased to the client as
    "suggested from current information" — never claimed to represent
    Bernardo's actual preference; the frontend must not word it as
    definitive either."""

    recommended: MissionCandidateRead | None
    alternatives: list[MissionCandidateRead]
    watch: list[MissionCandidateRead]
    generated_at: datetime


class StartMissionRequest(BaseModel):
    source_type: FocusSessionSourceType
    # Required for every source_type except 'manual'.
    source_id: str | None = Field(default=None, max_length=36)
    # Required for 'manual' (a freely-typed mission); optional override
    # (falls back to the source's own title) for every other source_type.
    title: str | None = Field(default=None, max_length=300)
    # Required for 'manual' if a domain applies; ignored for every other
    # source_type, since the domain is always resolved from the real
    # source server-side instead.
    domain_slug: str | None = None
    target_duration_minutes: int = Field(ge=FOCUS_SESSION_MIN_MINUTES, le=FOCUS_SESSION_MAX_MINUTES)


class PauseMissionRequest(BaseModel):
    pass


class ResumeMissionRequest(BaseModel):
    pass


class CompleteMissionRequest(BaseModel):
    completion_note: str | None = Field(default=None, max_length=1000)
    what_changed_note: str | None = Field(default=None, max_length=1000)


class AbandonMissionRequest(BaseModel):
    completion_note: str | None = Field(default=None, max_length=1000)


class FocusSessionRead(BaseModel):
    id: str
    title: str
    domain_slug: str | None
    source_type: str
    source_id: str | None
    source_title_snapshot: str | None
    status: FocusSessionStatus
    target_duration_minutes: int
    started_at: datetime | None
    paused_at: datetime | None
    accumulated_paused_seconds: int
    completed_at: datetime | None
    completion_note: str | None
    what_changed_note: str | None
    abandoned_reason: str | None
    elapsed_seconds: int
    remaining_seconds: int
    created_at: datetime
    updated_at: datetime


class CurrentMissionRead(BaseModel):
    session: FocusSessionRead | None
