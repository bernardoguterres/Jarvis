"""Phase 12A/12B: request/response models for the on-demand Home
situational briefing and its continuity (change detection, acknowledge,
snooze). Never includes a credential, a raw token, a scope string, or any
provider payload — every field here is already-normalized display data."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.briefing_service import SNOOZE_DURATION_LABELS


class BriefingSourceStatusRead(BaseModel):
    source_type: str
    status: str
    detail: str | None
    last_updated: datetime | None


class BriefingItemRead(BaseModel):
    id: str
    category: str
    tone: str
    title: str
    subtitle: str | None
    domain_slug: str | None
    source_type: str
    source_ids: list[str]
    reason: str
    source_timestamp: datetime | None
    freshness: str
    classification: str
    link_target: str | None
    fingerprint: str
    change_state: str
    pinned: bool = False
    pin_rank: int | None = None


class MissionFocusEntryRead(BaseModel):
    pin_id: str
    rank: int
    source_type: str
    domain_slug: str | None
    title: str
    subtitle: str | None
    next_action: str
    target_at: datetime | None
    blocker: str | None
    link_target: str | None
    available: bool
    resolved: bool
    change_state: str | None


class BriefingAcknowledgedOrSnoozedRead(BaseModel):
    stable_key: str
    kind: Literal["acknowledged", "snoozed"]
    title: str
    subtitle: str | None
    domain_slug: str | None
    link_target: str | None
    since: datetime
    until: datetime | None
    duration_key: str | None


class HomeBriefingRead(BaseModel):
    generated_at: datetime
    items: list[BriefingItemRead]
    sources: list[BriefingSourceStatusRead]
    include_body: bool
    include_mind: bool
    include_people: bool
    acknowledged_and_snoozed: list[BriefingAcknowledgedOrSnoozedRead]
    mission_focus: list[MissionFocusEntryRead]


class BriefingSettingsRead(BaseModel):
    include_body: bool
    include_mind: bool
    include_people: bool


class BriefingSettingsUpdateRequest(BaseModel):
    """MIND/PEOPLE are deliberately not settable here — Phase 12A defines
    no permitted MIND/PEOPLE source for the Home briefing at all (see
    app/briefing_service.py's module docstring), so the only real toggle
    is BODY. include_mind/include_people always persist as False."""

    include_body: bool


class BriefingSnapshotRead(BaseModel):
    id: str
    consumer: str
    trigger: str
    generated_at: datetime
    item_count: int


# The exact fixed, server-validated set of snooze durations — see
# app.briefing_service.SNOOZE_DURATION_LABELS, the single source of truth
# this schema's Literal type is derived from at import time, so the two
# can never silently drift apart.
SnoozeDurationKey = Literal["1h", "4h", "tomorrow_morning", "1w"]
assert set(SnoozeDurationKey.__args__) == set(SNOOZE_DURATION_LABELS)


class BriefingSnoozeRequest(BaseModel):
    duration: SnoozeDurationKey
    # Only meaningful for "tomorrow_morning"; ignored otherwise. Defaults
    # to app.briefing_service.DEFAULT_BRIEFING_TIMEZONE server-side when
    # omitted — never required from the client.
    timezone: str | None = None


class BriefingItemActionResult(BaseModel):
    stable_key: str
    suppressed: Literal["acknowledged", "snoozed"] | None
    message: str
