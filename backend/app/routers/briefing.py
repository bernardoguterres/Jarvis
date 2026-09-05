"""Phase 12A/12B: the on-demand Home situational briefing's HTTP surface,
plus its continuity endpoints (history, acknowledge, snooze, restore).

`GET /api/briefing/home` is a pure read from the caller's perspective —
assembling it never calls a model, Hermes, or mutates any *external*
source (see app/briefing_service.py); it does write to this module's own
presentation-state tables (the continuity ledger, the snapshot audit
trail). Acknowledge/snooze/restore are real, transactional local
mutations, but — per CLAUDE.md §12 — they control only what Jarvis shows,
never the Phase 8 external-action lifecycle, and never the original
Calendar/task/action/integration/routine/Health record.

There is no "Discuss with Jarvis" route here either, matching the Morning
Briefing routine's own pattern (app/routers/routines.py): the frontend
sends the briefing's own rendered text (now including each item's change
label) into a normal conversation turn through the existing,
already-model-using general-conversation endpoints — never a
briefing-specific bypass.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import briefing_service
from app.deps import get_db
from app.schemas_briefing import (
    BriefingAcknowledgedOrSnoozedRead,
    BriefingItemActionResult,
    BriefingItemRead,
    BriefingSettingsRead,
    BriefingSettingsUpdateRequest,
    BriefingSnapshotRead,
    BriefingSnoozeRequest,
    BriefingSourceStatusRead,
    HomeBriefingRead,
    MissionFocusEntryRead,
)

router = APIRouter(tags=["briefing"])


def _clock() -> datetime:
    return datetime.now(timezone.utc)


def _settings_to_read(settings) -> BriefingSettingsRead:
    return BriefingSettingsRead(
        include_body=settings.include_body,
        include_mind=settings.include_mind,
        include_people=settings.include_people,
    )


def _item_to_read(item: briefing_service.BriefingItem) -> BriefingItemRead:
    return BriefingItemRead(
        id=item.id,
        category=item.category,
        tone=item.tone,
        title=item.title,
        subtitle=item.subtitle,
        domain_slug=item.domain_slug,
        source_type=item.source_type,
        source_ids=list(item.source_ids),
        reason=item.reason,
        source_timestamp=item.source_timestamp,
        freshness=item.freshness,
        classification=item.classification,
        link_target=item.link_target,
        fingerprint=item.fingerprint,
        change_state=item.change_state,
        pinned=item.pinned,
        pin_rank=item.pin_rank,
    )


def _mission_focus_entry_to_read(entry: briefing_service.MissionFocusEntry) -> MissionFocusEntryRead:
    return MissionFocusEntryRead(
        pin_id=entry.pin_id,
        rank=entry.rank,
        source_type=entry.source_type,
        domain_slug=entry.domain_slug,
        title=entry.title,
        subtitle=entry.subtitle,
        next_action=entry.next_action,
        target_at=entry.target_at,
        blocker=entry.blocker,
        link_target=entry.link_target,
        available=entry.available,
        resolved=entry.resolved,
        change_state=entry.change_state,
    )


def _entry_to_read(entry: briefing_service.AcknowledgedOrSnoozedEntry) -> BriefingAcknowledgedOrSnoozedRead:
    return BriefingAcknowledgedOrSnoozedRead(
        stable_key=entry.stable_key,
        kind=entry.kind,
        title=entry.title,
        subtitle=entry.subtitle,
        domain_slug=entry.domain_slug,
        link_target=entry.link_target,
        since=entry.since,
        until=entry.until,
        duration_key=entry.duration_key,
    )


def _briefing_to_read(briefing: briefing_service.HomeBriefing) -> HomeBriefingRead:
    return HomeBriefingRead(
        generated_at=briefing.generated_at,
        items=[_item_to_read(item) for item in briefing.items],
        sources=[
            BriefingSourceStatusRead(
                source_type=s.source_type, status=s.status, detail=s.detail, last_updated=s.last_updated
            )
            for s in briefing.sources
        ],
        include_body=briefing.include_body,
        include_mind=briefing.include_mind,
        include_people=briefing.include_people,
        acknowledged_and_snoozed=[_entry_to_read(e) for e in briefing.acknowledged_and_snoozed],
        mission_focus=[_mission_focus_entry_to_read(e) for e in briefing.mission_focus],
    )


@router.get("/api/briefing/settings", response_model=BriefingSettingsRead)
def get_briefing_settings(db: Session = Depends(get_db)) -> BriefingSettingsRead:
    settings = briefing_service.get_or_create_settings(db)
    return _settings_to_read(settings)


@router.put("/api/briefing/settings", response_model=BriefingSettingsRead)
def update_briefing_settings(
    payload: BriefingSettingsUpdateRequest, db: Session = Depends(get_db)
) -> BriefingSettingsRead:
    settings = briefing_service.set_include_body(db, payload.include_body)
    return _settings_to_read(settings)


@router.get("/api/briefing/home", response_model=HomeBriefingRead)
def get_home_briefing(
    trigger: str = Query(default="home_view", pattern="^(home_view|home_refresh)$"),
    db: Session = Depends(get_db),
) -> HomeBriefingRead:
    """`trigger` distinguishes an ordinary view from an explicit Refresh
    click for audit purposes only (`BriefingSnapshot.trigger`) — both use
    the exact same 'home' comparison baseline, so refreshing can never
    itself manufacture a spurious change."""
    settings = briefing_service.get_or_create_settings(db)
    briefing = briefing_service.assemble_home_briefing(
        db,
        include_body=settings.include_body,
        include_mind=settings.include_mind,
        include_people=settings.include_people,
        now=_clock(),
        trigger=trigger,
    )
    return _briefing_to_read(briefing)


@router.get("/api/briefing/history", response_model=list[BriefingSnapshotRead])
def get_briefing_history(
    consumer: str = Query(default="home", pattern="^(home|morning_briefing)$"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[BriefingSnapshotRead]:
    rows = briefing_service.get_snapshot_history(db, consumer, limit)
    return [
        BriefingSnapshotRead(
            id=row.id, consumer=row.consumer, trigger=row.trigger, generated_at=row.generated_at,
            item_count=row.item_count,
        )
        for row in rows
    ]


@router.post("/api/briefing/items/{stable_key}/acknowledge", response_model=BriefingItemActionResult)
def acknowledge_briefing_item(stable_key: str, db: Session = Depends(get_db)) -> BriefingItemActionResult:
    try:
        briefing_service.acknowledge_item(db, stable_key, _clock())
    except briefing_service.BriefingActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BriefingItemActionResult(
        stable_key=stable_key, suppressed="acknowledged", message="Hidden this version from the briefing."
    )


@router.post("/api/briefing/items/{stable_key}/snooze", response_model=BriefingItemActionResult)
def snooze_briefing_item(
    stable_key: str, payload: BriefingSnoozeRequest, db: Session = Depends(get_db)
) -> BriefingItemActionResult:
    try:
        snooze = briefing_service.snooze_item(db, stable_key, payload.duration, _clock(), payload.timezone)
    except briefing_service.BriefingActionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    label = briefing_service.SNOOZE_DURATION_LABELS[payload.duration]
    return BriefingItemActionResult(
        stable_key=stable_key,
        suppressed="snoozed",
        message=f"Hidden from the briefing — {label.lower()} (until {snooze.snooze_until.isoformat()}).",
    )


@router.post("/api/briefing/items/{stable_key}/restore", response_model=BriefingItemActionResult)
def restore_briefing_item(stable_key: str, db: Session = Depends(get_db)) -> BriefingItemActionResult:
    try:
        restored = briefing_service.restore_item(db, stable_key, _clock())
    except briefing_service.BriefingActionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BriefingItemActionResult(
        stable_key=stable_key,
        suppressed=None,
        message="Restored to the briefing." if restored else "Nothing was hidden for this item.",
    )
