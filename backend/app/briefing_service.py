"""Phase 12A/12B: current situational briefing / attention assembler, and
briefing continuity (change detection, acknowledge, snooze).

Shared, deterministic, local-only logic reused by:

  1. app/routine_service.py's Morning Briefing routine (Phase 10B) — its
     per-section data gathering (today's Calendar events, open LIFE/PATH/
     BUILD records, the latest Google Health daily summary) now calls the
     helpers in this module, so the routine and the on-demand Home
     briefing below never independently re-derive (and potentially
     disagree about) the same underlying facts. The routine also records
     a lightweight `BriefingSnapshot` row (`consumer="morning_briefing"`)
     purely for audit/history — it never touches `BriefingItemState` or
     any acknowledge/snooze table, which are exclusively a Home concern
     (see §12B below).
  2. app/routers/briefing.py's on-demand Home "situational briefing" — a
     concise (3-5 item) NOW/NEXT/WATCH triage view, distinct from the
     Morning Briefing routine's own fuller per-domain listing.

Hard rules enforced by construction here (CLAUDE.md, Phase 12A/12B brief):

  * No model call, no Hermes call, anywhere in this module.
  * No action proposal is ever created and nothing is ever mutated on any
    external source — every function here only reads Jarvis's own
    already-locally-stored/synced data; acknowledge/snooze writes affect
    only this module's own presentation-state tables (§12B), never the
    original Calendar/task/action/integration/routine/Health record.
  * MIND and PEOPLE data is never read by the Home briefing at all
    (there is no code path from either domain's tables into
    `assemble_home_briefing`), regardless of the `include_mind`/
    `include_people` settings flags below — those flags exist for
    forward compatibility with `BriefingSettings` (mirroring the
    Morning Briefing routine's own per-domain opt-in shape) but gate
    nothing yet, since Phase 12A defines no permitted MIND/PEOPLE source
    for this view. If a MIND/PEOPLE source is ever added here, it must
    be gated behind its own flag exactly the way `include_body` gates
    Google Health below — never a default inclusion.
  * BODY (Google Health) is reported as plain, already-computed facts
    (a date, a count, a "days since last sync") — never a derived score,
    never a medical interpretation. Google Health's own unsupported
    scores (readiness/sleep/stress/cardio load) are not surfaced here,
    matching app/providers/google_health.py's UNSUPPORTED_METRICS.
  * Every `BriefingItem` carries enough provenance to audit: a stable
    identity key, the exact source row id(s), a human reason, a source
    timestamp (when one exists), a truthful freshness label, a content
    fingerprint, and whether it's a plain fact or (never yet used here)
    an explicitly labeled inference.

Phase 12B — continuity, in one paragraph: every candidate item carries two
separate deterministic identifiers. `id` (the "stable identity key")
represents the underlying concern across time (one Calendar event, one
task, one integration's sync health, ...) and is never expected to change
run to run for the same concern. `fingerprint` is a short stable hash of
only the specific normalized, typed, already-computed fields that are
considered meaningful for that source type (documented per-source below,
inline at each candidate-construction site) — never a raw provider
payload, secret, token, or untrusted text. Comparing these two values
against `BriefingItemState` (the persisted per-identity ledger) is what
produces the `new`/`changed`/`ongoing`/`resolved`/`reopened`
classification — see `_reconcile_ledger` for the exact rules, and
`docs/ARCHITECTURE.md` §16 / `docs/DECISIONS.md` D87 for the full account.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Domain
from app.models_actions import ActionProposal
from app.models_briefing import (
    BRIEFING_SETTINGS_SINGLETON_ID,
    BriefingAcknowledgement,
    BriefingItemState,
    BriefingSettings,
    BriefingSnapshot,
    BriefingSnooze,
)
from app.models_integrations import (
    CalendarCalendar,
    CalendarEventCache,
    GoogleHealthDailySummary,
    IntegrationConnection,
)
from app.models_memory import StructuredRecord
from app.models_mission_focus import MissionFocusPin
from app.models_routines import RoutineRun
from app.models_scheduler import IntegrationSyncSchedule

Category = Literal["now", "next", "watch"]
Tone = Literal["neutral", "attention", "failure"]
Freshness = Literal["current", "cached", "stale", "unavailable"]
Classification = Literal["factual", "inferred"]

# --- Tunables (documented here, not scattered as magic numbers) ---------

# A Calendar event starting within this many minutes (or already under
# way) counts as NOW; further out today is NEXT.
CALENDAR_IMMINENT_MINUTES = 30
# A structured record's due_date at-or-before today is NOW (overdue);
# within this many days is NEXT ("upcoming today/soon" per the brief).
DUE_SOON_DAYS = 3
# A cached integration's last successful sync older than this is reported
# as stale rather than silently treated as current.
CALENDAR_STALE_HOURS = 6
GOOGLE_HEALTH_STALE_DAYS = 3
# A failed action/routine run older than this no longer clutters WATCH.
RECENT_FAILURE_WINDOW_DAYS = 3
# A BUILD checkpoint is only worth a passive WATCH mention while genuinely
# fresh news, not a permanent fixture of every briefing.
RECENT_CHECKPOINT_WINDOW_DAYS = 2

# Deterministic tie-break bands for BriefingItem.priority (lower sorts
# first within its own category — see _sort_key). Documented explicitly
# rather than left as unexplained magic numbers, since these are Jarvis's
# own judgment calls, not something the product brief mandates precisely.
_PRIORITY_FAILED_ACTIONS = 5
_PRIORITY_PENDING_ACTIONS = 10
_PRIORITY_ROUTINE_FAILED = 15
_PRIORITY_INTEGRATION_ERROR = 20
_PRIORITY_INTEGRATION_STALE = 40
_PRIORITY_BODY_STALE = 50
_PRIORITY_BUILD_CHECKPOINT = 90
# Overdue tasks/deadlines always rank below an imminent Calendar event
# within NOW (a meeting starting in 10 minutes is more time-critical than
# a task that has already been overdue for days) — this band starts well
# above CALENDAR_IMMINENT_MINUTES's 0-30 range.
_PRIORITY_OVERDUE_BASE = 200
_PRIORITY_DUE_SOON_BASE = 1000

HOME_BRIEFING_MAX_ITEMS = 5

ALL_DOMAIN_SLUGS = ("body", "mind", "people", "path", "build", "life")

# --------------------------------------------------------------------------
# Phase 12B: continuity types and tunables
# --------------------------------------------------------------------------

ChangeState = Literal["new", "changed", "ongoing", "resolved", "reopened"]
SuppressKind = Literal["acknowledged", "snoozed"]

# A NEW/CHANGED/REOPENED item is nudged toward the front of its own
# category so genuinely new information doesn't get buried behind
# unchanged ongoing items competing for the same 5-item cap; an unchanged
# ONGOING item gets a small opposite nudge. Both are small relative to the
# priority bands above (§12A) so they can never cross a real priority-band
# boundary (e.g. never make an ongoing WATCH item outrank a genuinely new
# NOW item) — they only reorder within what was already a near-tie.
_CHANGE_PRIORITY_BOOST = 3
_ONGOING_PRIORITY_PENALTY = 1
# Resolved items are deliberately the lowest-priority tier in WATCH — they
# only ever occupy a cap slot that would otherwise be empty ("shown
# sparingly," per the Phase 12B brief).
_PRIORITY_RESOLVED = 1_000_000

# Snapshot spam prevention: two candidate-set generations for the same
# consumer within this window, with an identical content digest, reuse the
# existing snapshot row rather than inserting a new one (e.g. a double
# Refresh click, or a React effect double-invoke).
SNAPSHOT_DEDUPE_WINDOW_SECONDS = 60
# Bounded history, mirroring routine_service.py's ROUTINE_RUN_RETENTION_PER_TYPE.
SNAPSHOT_RETENTION_PER_CONSUMER = 200
# A resolved ledger row (e.g. a single day's Calendar event, which by
# construction gets a brand new identity every day) is only useful for a
# little while after resolution — pruned by cleanup_old_briefing_state()
# so a fast-churning daily source can never grow this table unboundedly.
LEDGER_RESOLVED_RETENTION_DAYS = 30
# Restored/expired acknowledge-and-snooze rows are kept for audit for a
# while, then pruned the same way; ACTIVE rows are never pruned.
ACK_SNOOZE_INACTIVE_RETENTION_DAYS = 30

# Snoozing offers a small, fixed, server-validated set of durations —
# never an arbitrary client-supplied timestamp (CLAUDE.md §12).
SNOOZE_DURATION_LABELS: dict[str, str] = {
    "1h": "1 hour",
    "4h": "4 hours",
    "tomorrow_morning": "Until tomorrow morning",
    "1w": "1 week",
}
# "Tomorrow morning" needs a timezone and an hour — Bernardo's own
# recorded Morning Briefing timezone (docs/ROADMAP.md Phase 10B) is reused
# as a sensible shared default; callers may override per-request (and
# tests do, to exercise DST) via SnoozeRequest.timezone.
DEFAULT_BRIEFING_TIMEZONE = "Europe/London"
SNOOZE_MORNING_HOUR = 8

# --------------------------------------------------------------------------
# Phase 12C: Mission Focus tunables
# --------------------------------------------------------------------------

# A pinned item with no inherent date-driven urgency (a WATCH-tier
# build_checkpoint/action_proposal, or a task/deadline with no due date)
# ranks here — below genuine failure/urgent signals (FAILED_ACTIONS=5,
# PENDING_ACTIONS=10, ROUTINE_FAILED=15, INTEGRATION_ERROR=20, all still
# more urgent) but above ordinary informational WATCH items
# (INTEGRATION_STALE=40, BODY_STALE=50, BUILD_CHECKPOINT=90) — the exact
# "genuinely urgent/failure states remain highest priority; active pins
# rank above ordinary non-urgent candidates" rule. `+ pin.rank` (1-5)
# breaks ties deterministically by Bernardo's own explicit ordering.
_PRIORITY_MISSION_FOCUS_WATCH_BASE = 25
# A pinned item that IS already NOW/NEXT on its own real-world merits (an
# overdue task, an imminent meeting) gets only a small nudge within its
# own category — it must never be able to cross into a different
# category or outrank a more urgent unpinned item just for being pinned.
_PIN_PRIORITY_NUDGE = 2


# --------------------------------------------------------------------------
# Persisted privacy settings
# --------------------------------------------------------------------------


def get_or_create_settings(session: Session) -> BriefingSettings:
    settings = session.get(BriefingSettings, BRIEFING_SETTINGS_SINGLETON_ID)
    if settings is None:
        settings = BriefingSettings(
            id=BRIEFING_SETTINGS_SINGLETON_ID, include_body=True, include_mind=False, include_people=False
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def set_include_body(session: Session, include_body: bool) -> BriefingSettings:
    """MIND/PEOPLE are never settable here — see BriefingSettingsUpdateRequest's
    docstring and this module's own module docstring for why."""
    settings = get_or_create_settings(session)
    settings.include_body = include_body
    settings.include_mind = False
    settings.include_people = False
    session.commit()
    session.refresh(settings)
    return settings


@dataclass(frozen=True)
class BriefingItem:
    id: str  # the stable identity key — see the module docstring's Phase 12B paragraph
    category: Category
    tone: Tone
    priority: int
    title: str
    subtitle: str | None
    domain_slug: str | None
    source_type: str
    source_ids: tuple[str, ...]
    reason: str
    source_timestamp: datetime | None
    freshness: Freshness
    classification: Classification
    link_target: str | None  # matches frontend NavigateTarget shape, or None
    fingerprint: str  # content fingerprint — see the module docstring's Phase 12B paragraph
    change_state: ChangeState = "new"  # overwritten by _reconcile_ledger; "new" is a safe default for callers that never reconcile
    # Phase 12C: set only when this exact candidate corresponds to an
    # active Mission Focus pin — never set by anything other than
    # `_merge_pin_into_item`/`_synthesize_pin_item` below, so `pinned`
    # always reflects a real, currently-active row in `mission_focus_pins`.
    pinned: bool = False
    pin_rank: int | None = None


@dataclass(frozen=True)
class SourceStatus:
    source_type: str
    status: Literal["ok", "stale", "unavailable", "not_connected"]
    detail: str | None
    last_updated: datetime | None


@dataclass(frozen=True)
class SourceEvaluation:
    """Whether a given source's candidate-gathering query itself
    succeeded this pass — independent of what it found. Only a source
    that evaluated `ok=True` may ever have one of its stable identities
    marked `resolved`; a source whose read failed this pass leaves every
    identity it might explain exactly as it was (CLAUDE.md's
    false-resolution-protection rule, Phase 12B)."""

    source_type: str
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class AcknowledgedOrSnoozedEntry:
    stable_key: str
    kind: SuppressKind
    title: str
    subtitle: str | None
    domain_slug: str | None
    link_target: str | None
    since: datetime
    until: datetime | None  # snoozes only; None for an indefinite acknowledgement
    duration_key: str | None  # snoozes only


@dataclass(frozen=True)
class HomeBriefing:
    generated_at: datetime
    items: list[BriefingItem]
    sources: list[SourceStatus]
    include_body: bool
    include_mind: bool
    include_people: bool
    acknowledged_and_snoozed: list[AcknowledgedOrSnoozedEntry] = field(default_factory=list)
    mission_focus: list["MissionFocusEntry"] = field(default_factory=list)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def domain_id_by_slug(session: Session, slug: str) -> str | None:
    domain = session.execute(select(Domain).where(Domain.slug == slug)).scalar_one_or_none()
    return domain.id if domain else None


def _record_payload(record: StructuredRecord) -> dict:
    try:
        return json.loads(record.payload_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _parse_due_date(raw: str | None) -> date_type | None:
    """`due_date` is a free-form, un-validated string field
    (app/structured_records.py) — never assume it parses. A value that
    doesn't parse as an ISO date is simply not date-triaged here; it
    remains fully visible in its own domain view."""
    if not raw:
        return None
    try:
        return date_type.fromisoformat(raw.strip())
    except ValueError:
        return None


def _format_date_display(d: date_type) -> str:
    """Human-facing date text for briefing subtitles/reasons — dd/mm/yyyy,
    Bernardo's explicit preference over a raw ISO 8601 string. Display
    only: fingerprint inputs and API data payloads elsewhere in this file
    deliberately keep using `.isoformat()`, since changing those would
    silently reshape stored fingerprints or machine-consumed fields."""
    return d.strftime("%d/%m/%Y")


def _format_datetime_display(dt: datetime) -> str:
    """Human-facing date+time text — dd/mm/yyyy, 24-hour clock. Converts
    to local time first: a stored UTC timestamp shown verbatim would be
    wrong by Bernardo's own UTC offset, and confusing for exactly the
    "when did this actually happen" question a briefing subtitle exists
    to answer."""
    # Every stored timestamp in this codebase is UTC by convention (see
    # `_utcnow()`), but SQLite's DateTime(timezone=True) doesn't actually
    # round-trip tzinfo — a naive value read back here is still UTC, not
    # already-local, so it must be labeled before converting.
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone().strftime("%d/%m/%Y, %H:%M")


def _fingerprint(fields: dict) -> str:
    """A short, stable, non-cryptographic content fingerprint over
    already-normalized, typed, display-safe fields only — never a raw
    provider payload, a secret, a token, or untrusted free text. Two
    calls with equal `fields` always produce the same digest (canonical
    JSON: sorted keys, fixed separators, non-JSON-native values coerced
    via `str`), which is the only property this needs — it is never used
    for anything security-sensitive."""
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Shared raw-data gathering — reused by app/routine_service.py so the
# routine and the Home briefing never independently re-derive the same
# underlying facts.
# --------------------------------------------------------------------------


def open_records(session: Session, domain_id: str, record_type: str, limit: int = 10) -> list[StructuredRecord]:
    """Open (never-archived) structured records of one type in one domain,
    most recent first — the exact shape every Morning Briefing section and
    every Home-briefing due-date check both need."""
    return (
        session.query(StructuredRecord)
        .filter(
            StructuredRecord.domain_id == domain_id,
            StructuredRecord.record_type == record_type,
            StructuredRecord.archived_at.is_(None),
        )
        .order_by(StructuredRecord.created_at.desc())
        .limit(limit)
        .all()
    )


def todays_calendar_events(session: Session, today: date_type) -> list[CalendarEventCache]:
    """Selected-calendar events falling on `today` (local-date match on
    the cached, already-synced data) — a manual/automatic sync (Phase
    9/10A) is what actually refreshes this cache; this function never
    calls Google itself."""
    rows = (
        session.query(CalendarEventCache)
        .join(CalendarCalendar)
        .filter(CalendarCalendar.selected.is_(True))
        .order_by(CalendarEventCache.start_datetime, CalendarEventCache.start_date)
        .all()
    )
    result = []
    for ev in rows:
        ev_date = ev.start_date or (ev.start_datetime.date() if ev.start_datetime else None)
        if ev_date == today:
            result.append(ev)
    return result


def latest_google_health_summary(session: Session) -> GoogleHealthDailySummary | None:
    return session.query(GoogleHealthDailySummary).order_by(GoogleHealthDailySummary.date.desc()).first()


# --------------------------------------------------------------------------
# Home briefing — candidate item gathering
# --------------------------------------------------------------------------


def _calendar_freshness(conn: IntegrationConnection | None, now: datetime) -> Freshness:
    if conn is None or conn.status != "connected":
        return "unavailable"
    if conn.last_sync_at is None:
        return "unavailable"
    if now - _as_aware(conn.last_sync_at) > timedelta(hours=CALENDAR_STALE_HOURS):
        return "stale"
    return "cached"


def _calendar_items(session: Session, now: datetime) -> list[BriefingItem]:
    conn = session.get(IntegrationConnection, "google_calendar")
    freshness = _calendar_freshness(conn, now)
    events = todays_calendar_events(session, now.date())
    items: list[BriefingItem] = []
    for ev in events:
        if ev.all_day or ev.start_datetime is None:
            category: Category = "next"
            tone: Tone = "neutral"
            priority = _PRIORITY_DUE_SOON_BASE + 900  # after every timed event, before nothing else
            subtitle = "All day"
        else:
            start = _as_aware(ev.start_datetime)
            end = _as_aware(ev.end_datetime) or start
            assert start is not None
            delta_minutes = (start - now).total_seconds() / 60
            if start <= now <= end or 0 <= delta_minutes <= CALENDAR_IMMINENT_MINUTES:
                category, tone = "now", "attention"
                priority = max(0, round(delta_minutes))
            elif delta_minutes > CALENDAR_IMMINENT_MINUTES:
                category, tone = "next", "neutral"
                priority = round(delta_minutes)
            else:
                continue  # already ended
            subtitle = start.strftime("%H:%M")
        # Fingerprint fields: title/start/end/all_day (the event's own
        # facts) plus `category` — a NOW/NEXT transition (an event
        # becoming imminent) is deliberately meaningful here, per the
        # Phase 12B rule that increasing urgency counts as a change.
        # Excluded: the exact `priority` (jitters every fetch as time
        # passes) and `freshness` (sync staleness is reported separately
        # via `SourceStatus`, not per-item).
        fp = _fingerprint(
            {
                "title": ev.title,
                "start": start.isoformat() if not (ev.all_day or ev.start_datetime is None) else None,
                "end": end.isoformat() if not (ev.all_day or ev.start_datetime is None) else None,
                "all_day": bool(ev.all_day),
                "category": category,
            }
        )
        items.append(
            BriefingItem(
                id=f"calendar_event:{ev.id}",
                category=category,
                tone=tone,
                priority=priority,
                title=ev.title,
                subtitle=subtitle,
                domain_slug="life",
                source_type="calendar_event",
                source_ids=(ev.id,),
                reason="Selected calendar event today",
                source_timestamp=ev.fetched_at,
                freshness=freshness,
                classification="factual",
                link_target="domain:life",
                fingerprint=fp,
            )
        )
    return items


def _dated_record_items(
    session: Session, domain_id: str, domain_slug: str, record_type: str, title_field: str, today: date_type
) -> list[BriefingItem]:
    items: list[BriefingItem] = []
    for r in open_records(session, domain_id, record_type):
        payload = _record_payload(r)
        due = _parse_due_date(payload.get("due_date"))
        if due is None:
            continue
        title = payload.get(title_field) or f"(untitled {record_type})"
        days_until = (due - today).days
        if days_until < 0:
            overdue_days = -days_until
            category: Category = "now"
            tone: Tone = "attention"
            priority = _PRIORITY_OVERDUE_BASE + max(0, 100 - min(overdue_days, 100))
            reason = f"overdue since {_format_date_display(due)}"
        elif days_until <= DUE_SOON_DAYS:
            category, tone = "next", "neutral"
            priority = _PRIORITY_DUE_SOON_BASE + days_until
            reason = f"due {_format_date_display(due)}"
        else:
            continue
        # Fingerprint fields: title/due_date/category. `category` again
        # deliberately captures a NEXT→NOW ("became overdue") transition
        # as a meaningful change; the exact `overdue_days`/`priority`
        # count is excluded so the fingerprint doesn't drift every single
        # day a task stays overdue.
        fp = _fingerprint({"title": title, "due_date": due.isoformat(), "category": category})
        items.append(
            BriefingItem(
                id=f"{record_type}:{r.id}",
                category=category,
                tone=tone,
                priority=priority,
                title=title,
                subtitle=f"Due {_format_date_display(due)}",
                domain_slug=domain_slug,
                source_type=record_type,
                source_ids=(r.id,),
                reason=reason,
                source_timestamp=r.created_at,
                freshness="current",
                classification="factual",
                link_target=f"domain:{domain_slug}",
                fingerprint=fp,
            )
        )
    return items


def _pending_actions_item(session: Session) -> BriefingItem | None:
    ids = [
        row[0]
        for row in session.query(ActionProposal.id).filter(ActionProposal.status.in_(("proposed", "approved"))).all()
    ]
    if not ids:
        return None
    # Fingerprint: the count plus the exact set of proposal ids, so the
    # count staying the same while the underlying set actually changed
    # (one resolved, a different one created) still counts as `changed`.
    fp = _fingerprint({"count": len(ids), "ids": sorted(ids)})
    return BriefingItem(
        id="action_proposal:pending",
        category="watch",
        tone="attention",
        priority=_PRIORITY_PENDING_ACTIONS,
        title=f"{len(ids)} action proposal{'s' if len(ids) != 1 else ''} awaiting your review",
        subtitle=None,
        domain_slug=None,
        source_type="action_proposal",
        source_ids=tuple(ids),
        reason="Proposed but not yet approved/executed",
        source_timestamp=None,
        freshness="current",
        classification="factual",
        link_target="actions_centre",
        fingerprint=fp,
    )


def _failed_actions_item(session: Session, now: datetime) -> BriefingItem | None:
    cutoff = now - timedelta(days=RECENT_FAILURE_WINDOW_DAYS)
    rows = (
        session.query(ActionProposal.id)
        .filter(ActionProposal.status == "failed", ActionProposal.updated_at >= cutoff)
        .all()
    )
    ids = [row[0] for row in rows]
    if not ids:
        return None
    fp = _fingerprint({"count": len(ids), "ids": sorted(ids)})
    return BriefingItem(
        id="action_proposal:failed",
        category="watch",
        tone="failure",
        priority=_PRIORITY_FAILED_ACTIONS,
        title=f"{len(ids)} action{'s' if len(ids) != 1 else ''} failed recently",
        subtitle=None,
        domain_slug=None,
        source_type="action_proposal",
        source_ids=tuple(ids),
        reason=f"Failed within the last {RECENT_FAILURE_WINDOW_DAYS} days",
        source_timestamp=None,
        freshness="current",
        classification="factual",
        link_target="actions_centre",
        fingerprint=fp,
    )


def _integration_watch_items(session: Session, now: datetime) -> list[BriefingItem]:
    # Identity is per-provider only (`integration_sync:{provider}`) — the
    # error-vs-stale distinction, and the exact error text, live in the
    # fingerprint instead of the identity key, so a provider's sync
    # health is tracked as ONE continuous concern across states (a
    # `stale` warning quietly becoming a hard `error` reads as `changed`,
    # not as one identity resolving while a brand new one appears).
    items: list[BriefingItem] = []
    for provider, label in (("google_calendar", "Google Calendar"), ("google_health", "Google Health")):
        conn = session.get(IntegrationConnection, provider)
        if conn is None or conn.status not in ("connected", "error"):
            continue  # never connected, or already genuinely disconnected — nothing to watch
        if conn.status == "error" or conn.last_sync_status in ("failed", "partial"):
            state = "failed" if conn.last_sync_status == "failed" else (conn.last_sync_status or "error")
            # last_sync_at is deliberately excluded from the fingerprint —
            # it advances on every retry even while the failure reason
            # itself is unchanged, which would otherwise make this
            # `changed` on every single sync attempt.
            fp = _fingerprint({"state": state, "last_error": conn.last_error})
            items.append(
                BriefingItem(
                    id=f"integration_sync:{provider}",
                    category="watch",
                    tone="failure",
                    priority=_PRIORITY_INTEGRATION_ERROR,
                    title=f"{label} sync {'failed' if conn.last_sync_status == 'failed' else conn.last_sync_status or 'reported an error'}",
                    subtitle=conn.last_error,
                    domain_slug=None,
                    source_type="integration_sync",
                    source_ids=(provider,),
                    reason=conn.last_error or "Last sync did not fully succeed",
                    source_timestamp=conn.last_sync_at,
                    freshness="unavailable" if conn.status == "error" else "stale",
                    classification="factual",
                    link_target="integrations_centre",
                    fingerprint=fp,
                )
            )
            continue
        schedule = session.get(IntegrationSyncSchedule, provider)
        if schedule is not None and schedule.enabled and conn.last_sync_at is not None:
            threshold = timedelta(minutes=schedule.interval_minutes * 4)
            if now - _as_aware(conn.last_sync_at) > threshold:
                fp = _fingerprint({"state": "stale"})
                items.append(
                    BriefingItem(
                        id=f"integration_sync:{provider}",
                        category="watch",
                        tone="attention",
                        priority=_PRIORITY_INTEGRATION_STALE,
                        title=f"{label} data has not synced recently",
                        subtitle=f"Last synced {_format_datetime_display(conn.last_sync_at)}",
                        domain_slug=None,
                        source_type="integration_sync",
                        source_ids=(provider,),
                        reason="Automatic sync is enabled but overdue",
                        source_timestamp=conn.last_sync_at,
                        freshness="stale",
                        classification="factual",
                        link_target="integrations_centre",
                        fingerprint=fp,
                    )
                )
    return items


def _routine_watch_items(session: Session, now: datetime) -> list[BriefingItem]:
    # Identity is per-routine-type (`routine_run:{routine_type}`), not
    # per-run — a *new* failing run of the same routine (a different
    # RoutineRun.id) is what the fingerprint captures as `changed`
    # (genuinely worth re-flagging), while the identity itself represents
    # the ongoing concern "does this routine currently run cleanly."
    items: list[BriefingItem] = []
    cutoff = now - timedelta(days=RECENT_FAILURE_WINDOW_DAYS)
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        run = (
            session.query(RoutineRun)
            .filter(RoutineRun.routine_type == routine_type, RoutineRun.outcome == "failed")
            .filter(RoutineRun.started_at >= cutoff)
            .order_by(RoutineRun.started_at.desc())
            .first()
        )
        if run is None:
            continue
        fp = _fingerprint({"run_id": run.id, "reason": run.reason})
        items.append(
            BriefingItem(
                id=f"routine_run:{routine_type}",
                category="watch",
                tone="failure",
                priority=_PRIORITY_ROUTINE_FAILED,
                title=f"{routine_type.replace('_', ' ').title()} failed to run",
                subtitle=run.reason,
                domain_slug=None,
                source_type="routine_run",
                source_ids=(run.id,),
                reason=run.reason or "Routine run failed",
                source_timestamp=run.started_at,
                freshness="current",
                classification="factual",
                link_target="routine_centre",
                fingerprint=fp,
            )
        )
    return items


def _build_checkpoint_item(session: Session, now: datetime) -> BriefingItem | None:
    build_id = domain_id_by_slug(session, "build")
    if build_id is None:
        return None
    rows = open_records(session, build_id, "build_checkpoint", limit=1)
    if not rows:
        return None
    record = rows[0]
    created = _as_aware(record.created_at)
    if created is None or now - created > timedelta(days=RECENT_CHECKPOINT_WINDOW_DAYS):
        return None
    payload = _record_payload(record)
    project = payload.get("project", "a project")
    summary = payload.get("summary", "")
    fp = _fingerprint({"project": project, "summary": summary})
    return BriefingItem(
        id=f"build_checkpoint:{record.id}",
        category="watch",
        tone="neutral",
        priority=_PRIORITY_BUILD_CHECKPOINT,
        title=f"New checkpoint logged: {project}",
        subtitle=summary or None,
        domain_slug="build",
        source_type="build_checkpoint",
        source_ids=(record.id,),
        reason="Logged within the last day",
        source_timestamp=record.created_at,
        freshness="current",
        classification="factual",
        link_target="domain:build",
        fingerprint=fp,
    )


def _body_watch_item(session: Session, now: datetime) -> BriefingItem | None:
    # Identity is a fixed slot (`google_health:freshness`) — there is only
    # ever one "is BODY data fresh enough" concern, not one per summary
    # row. The fingerprint intentionally buckets to a coarse state
    # (`no_data` / `stale`) rather than the exact day-count, which would
    # otherwise make this `changed` every single day it stays stale.
    conn = session.get(IntegrationConnection, "google_health")
    if conn is None or conn.status != "connected":
        return None  # never connected / disconnected — Integrations Centre already says so
    latest = latest_google_health_summary(session)
    if latest is None:
        return BriefingItem(
            id="google_health:freshness",
            category="watch",
            tone="attention",
            priority=_PRIORITY_BODY_STALE,
            title="No Google Health data synced yet",
            subtitle=None,
            domain_slug="body",
            source_type="google_health",
            source_ids=("google_health",),
            reason="Connected, but no daily summary has ever synced",
            source_timestamp=None,
            freshness="unavailable",
            classification="factual",
            link_target="domain:body",
            fingerprint=_fingerprint({"state": "no_data"}),
        )
    days_stale = (now.date() - latest.date).days
    if days_stale < GOOGLE_HEALTH_STALE_DAYS:
        return None  # fresh enough — no noise, per "don't force headings with nothing useful"
    return BriefingItem(
        id="google_health:freshness",
        category="watch",
        tone="attention",
        priority=_PRIORITY_BODY_STALE,
        title=f"Health data last synced {days_stale} days ago",
        subtitle=f"Most recent summary: {_format_date_display(latest.date)}",
        domain_slug="body",
        source_type="google_health",
        source_ids=(latest.id,),
        reason=f"No newer daily summary than {_format_date_display(latest.date)}",
        source_timestamp=latest.fetched_at,
        freshness="stale",
        classification="factual",
        link_target="domain:body",
        fingerprint=_fingerprint({"state": "stale"}),
    )


def _source_statuses(session: Session, now: datetime) -> list[SourceStatus]:
    statuses = []
    for provider, label in (("google_calendar", "calendar"), ("google_health", "google_health")):
        conn = session.get(IntegrationConnection, provider)
        if conn is None or conn.status == "disconnected":
            statuses.append(SourceStatus(label, "not_connected", None, None))
        elif conn.status == "error":
            statuses.append(SourceStatus(label, "unavailable", conn.last_error, conn.last_sync_at))
        elif label == "calendar" and _calendar_freshness(conn, now) == "stale":
            statuses.append(SourceStatus(label, "stale", "Last sync older than expected", conn.last_sync_at))
        else:
            statuses.append(SourceStatus(label, "ok", None, conn.last_sync_at))
    return statuses


# --------------------------------------------------------------------------
# Phase 12C: Mission Focus — resolving a pinned source directly by id,
# bypassing the normal ephemeral inclusion windows (a pin's whole point is
# staying visible beyond them), and merging pin metadata into the
# briefing's existing candidate/ledger/change-state machinery rather than
# building a second, parallel one.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PinnedSourceInfo:
    domain_slug: str | None
    title: str
    subtitle: str | None
    category: Category
    tone: Tone
    link_target: str | None
    source_timestamp: datetime | None
    resolved: bool  # the underlying source has genuinely concluded (archived/executed/denied/expired)
    natural_fields: dict  # the same fields that source type's *natural* candidate would fingerprint on


@dataclass(frozen=True)
class MissionFocusEntry:
    """One row of the always-visible Mission Focus rail — computed for
    every active pin regardless of whether its corresponding candidate
    made the capped unified feed this pass."""

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
    available: bool  # False only if the source row itself could not be found at all
    resolved: bool  # True if the (still-resolvable) source has genuinely concluded
    change_state: ChangeState | None


def resolve_pin_source(session: Session, source_type: str, source_id: str, now: datetime) -> PinnedSourceInfo | None:
    """Resolves a Mission Focus-eligible source directly by id. Returns
    `None` only when the row genuinely does not exist (or its own type
    doesn't match `source_type`) — a source that has since concluded
    (archived/executed/denied/expired) is still returned, with
    `resolved=True`, so it can be reported truthfully rather than
    silently vanishing the moment it's no longer "current." Never raises;
    callers wrap this in their own try/except for false-resolution
    protection, exactly like every other source in this module."""
    if source_type in ("life_task", "path_deadline", "build_checkpoint"):
        record = session.get(StructuredRecord, source_id)
        if record is None or record.record_type != source_type:
            return None
        domain = session.get(Domain, record.domain_id)
        domain_slug = domain.slug if domain else None
        payload = _record_payload(record)
        resolved = record.archived_at is not None
        if source_type == "build_checkpoint":
            project = payload.get("project", "a project")
            summary = payload.get("summary", "")
            title = f"{project}: {summary}" if summary else project
            category: Category = "watch"
            tone: Tone = "neutral"
            subtitle = summary or None
            natural_fields = {"project": project, "summary": summary, "resolved": resolved}
        else:
            title = payload.get("title") or f"(untitled {source_type})"
            due = _parse_due_date(payload.get("due_date"))
            if due is None:
                category, tone, subtitle = "watch", "neutral", None
            else:
                days_until = (due - now.date()).days
                if days_until < 0:
                    category, tone = "now", "attention"
                elif days_until <= DUE_SOON_DAYS:
                    category, tone = "next", "neutral"
                else:
                    category, tone = "watch", "neutral"
                subtitle = f"Due {_format_date_display(due)}"
            natural_fields = {
                "title": title,
                "due_date": payload.get("due_date"),
                "category": category,
                "resolved": resolved,
            }
        return PinnedSourceInfo(
            domain_slug=domain_slug,
            title=title,
            subtitle=subtitle,
            category=category,
            tone=tone,
            link_target=f"domain:{domain_slug}" if domain_slug else None,
            source_timestamp=record.created_at,
            resolved=resolved,
            natural_fields=natural_fields,
        )

    if source_type == "calendar_event":
        ev = session.get(CalendarEventCache, source_id)
        if ev is None:
            return None
        if ev.all_day or ev.start_datetime is None:
            category, tone, subtitle = "watch", "neutral", "All day"
            start_iso = end_iso = None
        else:
            start = _as_aware(ev.start_datetime)
            end = _as_aware(ev.end_datetime) or start
            assert start is not None
            delta_minutes = (start - now).total_seconds() / 60
            if start <= now <= end or 0 <= delta_minutes <= CALENDAR_IMMINENT_MINUTES:
                category, tone = "now", "attention"
            elif delta_minutes > CALENDAR_IMMINENT_MINUTES:
                category, tone = "next", "neutral"
            else:
                category, tone = "watch", "neutral"  # already ended — still shown, since it's pinned
            subtitle = start.strftime("%H:%M")
            start_iso, end_iso = start.isoformat(), end.isoformat()
        natural_fields = {
            "title": ev.title,
            "start": start_iso,
            "end": end_iso,
            "all_day": bool(ev.all_day),
            "category": category,
        }
        return PinnedSourceInfo(
            domain_slug="life",
            title=ev.title,
            subtitle=subtitle,
            category=category,
            tone=tone,
            link_target="domain:life",
            source_timestamp=ev.fetched_at,
            resolved=False,
            natural_fields=natural_fields,
        )

    if source_type == "action_proposal":
        proposal = session.get(ActionProposal, source_id)
        if proposal is None:
            return None
        domain_slug = None
        if proposal.domain_id is not None:
            domain = session.get(Domain, proposal.domain_id)
            domain_slug = domain.slug if domain else None
        resolved = proposal.status in ("succeeded", "denied", "expired", "failed")
        title = proposal.expected_effect or proposal.capability_id
        tone = (
            "failure"
            if proposal.status == "failed"
            else ("attention" if proposal.status in ("proposed", "approved") else "neutral")
        )
        natural_fields = {"status": proposal.status, "expected_effect": proposal.expected_effect}
        return PinnedSourceInfo(
            domain_slug=domain_slug,
            title=title,
            subtitle=f"status: {proposal.status}",
            category="watch",
            tone=tone,
            link_target="actions_centre",
            source_timestamp=proposal.created_at,
            resolved=resolved,
            natural_fields=natural_fields,
        )

    return None


def _pin_fields(pin: "MissionFocusPin") -> dict:
    return {
        "rank": pin.rank,
        "next_action": pin.next_action,
        "blocker": pin.blocker,
        "target_at": pin.target_at.isoformat() if pin.target_at else None,
    }


def _pin_priority(category: Category, base_priority: int, rank: int) -> int:
    if category == "watch":
        return min(base_priority, _PRIORITY_MISSION_FOCUS_WATCH_BASE + rank)
    return max(0, base_priority - _PIN_PRIORITY_NUDGE)


def _merge_pin_into_item(item: BriefingItem, pin: "MissionFocusPin") -> BriefingItem:
    """A pin whose source already produced a natural candidate this pass
    (e.g. an overdue pinned task) — attach pin metadata without discarding
    the natural, real-world-derived category/tone/priority; only nudge
    priority within the same category (`_pin_priority`)."""
    combined_fp = _fingerprint({"natural": item.fingerprint, **_pin_fields(pin)})
    return dataclasses.replace(
        item,
        fingerprint=combined_fp,
        priority=_pin_priority(item.category, item.priority, pin.rank),
        pinned=True,
        pin_rank=pin.rank,
    )


def _synthesize_pin_item(pin: "MissionFocusPin", info: PinnedSourceInfo) -> BriefingItem:
    """A pin whose source did NOT produce a natural candidate this pass
    (e.g. a BUILD checkpoint older than the normal 2-day window, or a
    PATH deadline further out than the normal 3-day window) — the whole
    point of pinning is staying visible beyond those ephemeral windows."""
    stable_key = f"{pin.source_type}:{pin.source_id}"
    natural_fp = _fingerprint(info.natural_fields)
    combined_fp = _fingerprint({"natural": natural_fp, **_pin_fields(pin)})
    base_priority = {
        "now": _PRIORITY_OVERDUE_BASE,
        "next": _PRIORITY_DUE_SOON_BASE,
        "watch": _PRIORITY_MISSION_FOCUS_WATCH_BASE,
    }[info.category]
    return BriefingItem(
        id=stable_key,
        category=info.category,
        tone=info.tone,
        priority=_pin_priority(info.category, base_priority + pin.rank, pin.rank),
        title=info.title,
        subtitle=info.subtitle,
        domain_slug=info.domain_slug,
        source_type=pin.source_type,
        source_ids=(pin.source_id,),
        reason=f"Pinned to Mission Focus (#{pin.rank}): {pin.next_action}",
        source_timestamp=info.source_timestamp,
        freshness="current",
        classification="factual",
        link_target=info.link_target,
        fingerprint=combined_fp,
        pinned=True,
        pin_rank=pin.rank,
    )


def _unavailable_pin_item(pin: "MissionFocusPin") -> BriefingItem:
    """The pin's source row itself could not be found at all (e.g. a
    deleted structured record, or a Calendar event long rolled out of the
    sync cache). Reported truthfully and persistently — using the frozen
    `source_title_snapshot` — rather than silently vanishing, since the
    pin itself still exists until Bernardo explicitly removes it."""
    stable_key = f"{pin.source_type}:{pin.source_id}"
    fp = _fingerprint({"natural": "unavailable", **_pin_fields(pin)})
    return BriefingItem(
        id=stable_key,
        category="watch",
        tone="failure",
        priority=_PRIORITY_MISSION_FOCUS_WATCH_BASE + pin.rank,
        title=pin.source_title_snapshot or f"({pin.source_type})",
        subtitle=None,
        domain_slug=pin.domain_slug,
        source_type=pin.source_type,
        source_ids=(pin.source_id,),
        reason="This pinned source is no longer available.",
        source_timestamp=None,
        freshness="unavailable",
        classification="factual",
        link_target=None,
        fingerprint=fp,
        pinned=True,
        pin_rank=pin.rank,
    )


def _gather_mission_focus(
    session: Session, candidates: list[BriefingItem], now: datetime
) -> tuple[list[BriefingItem], dict[str, PinnedSourceInfo | None]]:
    """Merges active-pin metadata into `candidates` in place (returning a
    new list — candidates themselves are frozen dataclasses) and returns
    the resolved info for each pin (by pin id) for the rail to reuse
    without a second round of queries. A single pin's resolution failure
    never affects any other pin or any unrelated candidate — caught here,
    per pin, exactly like every other source in `_gather_candidates`."""
    pins = (
        session.query(MissionFocusPin)
        .filter(MissionFocusPin.status == "active")
        .order_by(MissionFocusPin.rank)
        .all()
    )
    by_id = {item.id: idx for idx, item in enumerate(candidates)}
    result = list(candidates)
    resolved_info: dict[str, PinnedSourceInfo | None] = {}

    for pin in pins:
        stable_key = f"{pin.source_type}:{pin.source_id}"
        try:
            info = resolve_pin_source(session, pin.source_type, pin.source_id, now)
        except Exception:  # a single pin's lookup must never crash the briefing
            resolved_info[pin.id] = None
            continue
        resolved_info[pin.id] = info

        if info is None:
            item = _unavailable_pin_item(pin)
        elif stable_key in by_id:
            item = _merge_pin_into_item(result[by_id[stable_key]], pin)
        else:
            item = _synthesize_pin_item(pin, info)

        if stable_key in by_id:
            result[by_id[stable_key]] = item
        else:
            by_id[stable_key] = len(result)
            result.append(item)

    return result, resolved_info


def build_mission_focus_rail(
    session: Session, change_states: dict[str, ChangeState], resolved_info: dict[str, PinnedSourceInfo | None], now: datetime
) -> list[MissionFocusEntry]:
    """The always-visible rail — every active pin, in rank order,
    regardless of whether its item made the capped unified feed this
    pass. Never itself capped beyond the schema's own 5-active-pin limit."""
    pins = (
        session.query(MissionFocusPin)
        .filter(MissionFocusPin.status == "active")
        .order_by(MissionFocusPin.rank)
        .all()
    )
    entries = []
    for pin in pins:
        info = resolved_info.get(pin.id)
        stable_key = f"{pin.source_type}:{pin.source_id}"
        change_state = change_states.get(stable_key)
        if info is None:
            entries.append(
                MissionFocusEntry(
                    pin_id=pin.id,
                    rank=pin.rank,
                    source_type=pin.source_type,
                    domain_slug=pin.domain_slug,
                    title=pin.source_title_snapshot or f"({pin.source_type})",
                    subtitle=None,
                    next_action=pin.next_action,
                    target_at=pin.target_at,
                    blocker=pin.blocker,
                    link_target=None,
                    available=False,
                    resolved=False,
                    change_state=change_state,
                )
            )
        else:
            entries.append(
                MissionFocusEntry(
                    pin_id=pin.id,
                    rank=pin.rank,
                    source_type=pin.source_type,
                    domain_slug=pin.domain_slug,
                    title=info.title,
                    subtitle=info.subtitle,
                    next_action=pin.next_action,
                    target_at=pin.target_at,
                    blocker=pin.blocker,
                    link_target=info.link_target,
                    available=True,
                    resolved=info.resolved,
                    change_state=change_state,
                )
            )
    return entries


_CATEGORY_RANK: dict[Category, int] = {"now": 0, "next": 1, "watch": 2}


def _sort_key(item: BriefingItem) -> tuple:
    return (_CATEGORY_RANK[item.category], item.priority, item.domain_slug or "~", item.source_type, item.source_ids)


def _dedupe(items: list[BriefingItem]) -> list[BriefingItem]:
    """Keyed on the stable identity (`id`) alone — two candidates sharing
    an identity is always a bug upstream (each gathering function owns a
    disjoint identity namespace by construction), so this is a defensive
    backstop, not the primary correctness mechanism."""
    seen: set[str] = set()
    result = []
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _gather_candidates(
    session: Session, *, include_body: bool, now: datetime
) -> tuple[list[BriefingItem], dict[str, SourceEvaluation]]:
    """Gathers the full, un-capped candidate set, isolating each source's
    failure from every other — a source whose query raises is recorded as
    `SourceEvaluation(ok=False)` and contributes zero candidates rather
    than crashing the whole assembly, and (critically) rather than making
    its previously-active identities look resolved (see `_reconcile_ledger`,
    the false-resolution-protection rule)."""
    items: list[BriefingItem] = []
    evaluations: dict[str, SourceEvaluation] = {}

    def _safe(source_type: str, fn: Callable[[], list[BriefingItem]]) -> None:
        try:
            items.extend(fn())
            evaluations[source_type] = SourceEvaluation(source_type, ok=True)
        except Exception as exc:  # a single source's failure must never crash the whole briefing
            evaluations[source_type] = SourceEvaluation(source_type, ok=False, detail=type(exc).__name__)

    _safe("calendar_event", lambda: _calendar_items(session, now))

    if (life_id := domain_id_by_slug(session, "life")) is not None:
        _safe("life_task", lambda: _dated_record_items(session, life_id, "life", "life_task", "title", now.date()))
    else:
        evaluations["life_task"] = SourceEvaluation("life_task", ok=True)
    if (path_id := domain_id_by_slug(session, "path")) is not None:
        _safe(
            "path_deadline",
            lambda: _dated_record_items(session, path_id, "path", "path_deadline", "title", now.date()),
        )
    else:
        evaluations["path_deadline"] = SourceEvaluation("path_deadline", ok=True)

    def _pending_and_failed() -> list[BriefingItem]:
        out = []
        if (pending := _pending_actions_item(session)) is not None:
            out.append(pending)
        if (failed := _failed_actions_item(session, now)) is not None:
            out.append(failed)
        return out

    _safe("action_proposal", _pending_and_failed)
    _safe("integration_sync", lambda: _integration_watch_items(session, now))
    _safe("routine_run", lambda: _routine_watch_items(session, now))

    def _checkpoint() -> list[BriefingItem]:
        item = _build_checkpoint_item(session, now)
        return [item] if item is not None else []

    _safe("build_checkpoint", _checkpoint)

    if include_body:
        def _body() -> list[BriefingItem]:
            item = _body_watch_item(session, now)
            return [item] if item is not None else []

        _safe("google_health", _body)
    else:
        evaluations["google_health"] = SourceEvaluation("google_health", ok=True)

    return _dedupe(items), evaluations


def _reconcile_ledger(
    session: Session, candidates: list[BriefingItem], evaluations: dict[str, SourceEvaluation], now: datetime
) -> tuple[dict[str, ChangeState], list[BriefingItem]]:
    """The Phase 12B continuity core. Compares `candidates` (the FULL
    un-capped set — priority-cap churn must never be mistaken for a real
    change) against `BriefingItemState`, the persisted per-identity
    ledger, and returns (1) each candidate's `change_state` and (2) a list
    of synthesized `resolved`-state display items for identities that
    were active and are now genuinely gone.

    Rules, exactly:
      * no existing ledger row  -> `new`; a row is inserted.
      * existing row, status == 'resolved' -> `reopened`; reactivated.
      * existing row, status == 'active', fingerprint unchanged -> `ongoing`.
      * existing row, status == 'active', fingerprint changed -> `changed`.
      * an 'active' row whose identity is NOT in `candidates` this pass is
        marked `resolved` ONLY IF that identity's `source_type` evaluated
        successfully this pass (see `_gather_candidates`) — otherwise it
        is left untouched (still 'active'), so a source read failure can
        never manufacture a false resolution, delete acknowledgement
        history, or silently drop a still-real concern.
    """
    change_states: dict[str, ChangeState] = {}
    candidate_by_key = {item.id: item for item in candidates}

    existing_rows = {
        row.stable_key: row
        for row in session.query(BriefingItemState)
        .filter(BriefingItemState.stable_key.in_(list(candidate_by_key)))
        .all()
    }

    for item in candidates:
        row = existing_rows.get(item.id)
        if row is None:
            row = BriefingItemState(
                stable_key=item.id,
                source_type=item.source_type,
                domain_slug=item.domain_slug,
                status="active",
                current_fingerprint=item.fingerprint,
                last_title=item.title,
                last_subtitle=item.subtitle,
                last_category=item.category,
                last_link_target=item.link_target,
                first_seen_at=now,
                last_active_at=now,
                last_changed_at=now,
                reopened_count=0,
            )
            session.add(row)
            change_states[item.id] = "new"
        elif row.status == "resolved":
            row.status = "active"
            row.reopened_count += 1
            row.current_fingerprint = item.fingerprint
            row.last_active_at = now
            row.last_changed_at = now
            change_states[item.id] = "reopened"
        elif row.current_fingerprint != item.fingerprint:
            row.current_fingerprint = item.fingerprint
            row.last_active_at = now
            row.last_changed_at = now
            change_states[item.id] = "changed"
        else:
            row.last_active_at = now
            change_states[item.id] = "ongoing"
        # Always refresh the cached display snapshot on an active pass —
        # this is what lets a future resolution be reported with a real,
        # current-as-of-last-sighting title rather than a stale one.
        row.last_title = item.title
        row.last_subtitle = item.subtitle
        row.last_category = item.category
        row.last_link_target = item.link_target

    resolved_items: list[BriefingItem] = []
    active_rows = session.query(BriefingItemState).filter(BriefingItemState.status == "active").all()
    for row in active_rows:
        if row.stable_key in candidate_by_key:
            continue
        evaluation = evaluations.get(row.source_type)
        if evaluation is None or not evaluation.ok:
            continue  # false-resolution protection — leave exactly as it was
        row.status = "resolved"
        row.last_resolved_at = now
        resolved_items.append(
            BriefingItem(
                id=row.stable_key,
                category="watch",
                tone="neutral",
                priority=_PRIORITY_RESOLVED,
                title=row.last_title,
                subtitle=None,
                domain_slug=row.domain_slug,
                source_type=row.source_type,
                source_ids=(),
                reason="This condition no longer applies.",
                source_timestamp=now,
                freshness="current",
                classification="factual",
                link_target=row.last_link_target,
                fingerprint=row.current_fingerprint or "",
                change_state="resolved",
            )
        )

    return change_states, resolved_items


def _apply_change_state(item: BriefingItem, change_state: ChangeState) -> BriefingItem:
    """Returns a copy of `item` with `change_state` set and `priority`
    nudged per §8's ranking refinement (documented on the tunables
    above) — never crossing a priority-band boundary, only reordering a
    near-tie within the same category."""
    if change_state in ("new", "changed", "reopened"):
        priority = max(0, item.priority - _CHANGE_PRIORITY_BOOST)
    elif change_state == "ongoing":
        priority = item.priority + _ONGOING_PRIORITY_PENALTY
    else:
        priority = item.priority
    return dataclasses.replace(item, change_state=change_state, priority=priority)


def is_suppressed(session: Session, stable_key: str, fingerprint: str, now: datetime) -> SuppressKind | None:
    """Whether the exact (stable_key, fingerprint) pair is currently
    hidden from the main briefing — an active acknowledgement, or an
    active, not-yet-expired snooze. A fingerprint change always makes
    this return None again (CLAUDE.md's "must immediately break if the
    item materially changes" rule) — it falls out structurally, since the
    lookup key includes the fingerprint."""
    ack = (
        session.query(BriefingAcknowledgement)
        .filter(
            BriefingAcknowledgement.stable_key == stable_key,
            BriefingAcknowledgement.fingerprint == fingerprint,
            BriefingAcknowledgement.status == "active",
        )
        .first()
    )
    if ack is not None:
        return "acknowledged"
    snooze = (
        session.query(BriefingSnooze)
        .filter(
            BriefingSnooze.stable_key == stable_key,
            BriefingSnooze.fingerprint == fingerprint,
            BriefingSnooze.status == "active",
            BriefingSnooze.snooze_until > now,
        )
        .first()
    )
    if snooze is not None:
        return "snoozed"
    return None


def expire_due_snoozes(session: Session, now: datetime) -> int:
    """Flips any active snooze whose window has passed to `expired` — a
    cheap, bounded, precisely-scoped UPDATE, called at the start of every
    `assemble_home_briefing` so an expired snooze's item reliably
    reappears on the very next fetch."""
    due = (
        session.query(BriefingSnooze)
        .filter(BriefingSnooze.status == "active", BriefingSnooze.snooze_until <= now)
        .all()
    )
    for row in due:
        row.status = "expired"
    return len(due)


def _content_digest(pairs: list[tuple[str, str]]) -> str:
    canonical = json.dumps(sorted(pairs), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def record_snapshot(
    session: Session, *, consumer: str, trigger: str, item_keys: list[tuple[str, str]], now: datetime
) -> BriefingSnapshot:
    """Records one candidate-set generation pass for audit/history and
    spam-prevention. `item_keys` is the full candidate set's
    `(stable_key, fingerprint)` pairs — for Home this is the real
    per-item continuity data; the Morning Briefing routine passes a
    lighter-weight equivalent derived from its own rendered output (see
    `app/routine_service.py`). If the most recent snapshot for this exact
    `consumer` has an identical digest and was generated within
    `SNAPSHOT_DEDUPE_WINDOW_SECONDS`, that existing row is reused rather
    than inserting a near-duplicate (e.g. a double Refresh click)."""
    digest = _content_digest(item_keys)
    latest = (
        session.query(BriefingSnapshot)
        .filter(BriefingSnapshot.consumer == consumer)
        .order_by(BriefingSnapshot.generated_at.desc())
        .first()
    )
    if (
        latest is not None
        and latest.content_digest == digest
        and (now - _as_aware(latest.generated_at)) <= timedelta(seconds=SNAPSHOT_DEDUPE_WINDOW_SECONDS)
    ):
        return latest

    snapshot = BriefingSnapshot(
        consumer=consumer, trigger=trigger, generated_at=now, item_count=len(item_keys), content_digest=digest
    )
    session.add(snapshot)
    session.flush()  # autoflush=False in this project — need the row visible for the retention query below

    # Bounded retention, same pattern as routine_service._trim_history.
    all_ids = [
        row[0]
        for row in session.query(BriefingSnapshot.id)
        .filter(BriefingSnapshot.consumer == consumer)
        .order_by(BriefingSnapshot.generated_at.desc())
        .all()
    ]
    stale_ids = all_ids[SNAPSHOT_RETENTION_PER_CONSUMER:]
    if stale_ids:
        session.execute(delete(BriefingSnapshot).where(BriefingSnapshot.id.in_(stale_ids)))

    return snapshot


def _tomorrow_morning_utc(now_utc: datetime, tz_name: str, hour: int = SNOOZE_MORNING_HOUR) -> datetime:
    """DST-safe "tomorrow morning" — constructs the candidate directly in
    the target IANA timezone's wall-clock terms (never a fixed-offset
    timedelta added to a UTC instant), mirroring
    `routine_service._next_occurrence_utc`."""
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    tomorrow_local = (now_local + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return tomorrow_local.astimezone(timezone.utc)


class BriefingActionError(Exception):
    pass


def _current_ledger_row(session: Session, stable_key: str) -> BriefingItemState:
    row = (
        session.query(BriefingItemState)
        .filter(BriefingItemState.stable_key == stable_key, BriefingItemState.status == "active")
        .one_or_none()
    )
    if row is None or row.current_fingerprint is None:
        raise BriefingActionError("Unknown or no longer active briefing item.")
    return row


def acknowledge_item(session: Session, stable_key: str, now: datetime) -> BriefingAcknowledgement:
    """Acknowledgement is a local presentation preference — it never
    touches the underlying Calendar event, task, action proposal,
    integration, routine, or Health record. Always acknowledges the
    item's CURRENT fingerprint (looked up server-side from the ledger,
    never client-supplied), so a stale/faked fingerprint can never be
    submitted."""
    row = _current_ledger_row(session, stable_key)
    existing = (
        session.query(BriefingAcknowledgement)
        .filter(
            BriefingAcknowledgement.stable_key == stable_key,
            BriefingAcknowledgement.fingerprint == row.current_fingerprint,
            BriefingAcknowledgement.status == "active",
        )
        .one_or_none()
    )
    if existing is not None:
        existing.acknowledged_at = _as_aware(existing.acknowledged_at)
        return existing
    ack = BriefingAcknowledgement(
        stable_key=stable_key,
        fingerprint=row.current_fingerprint,
        status="active",
        title_snapshot=row.last_title,
        subtitle_snapshot=row.last_subtitle,
        domain_slug_snapshot=row.domain_slug,
        link_target_snapshot=row.last_link_target,
        acknowledged_at=now,
    )
    session.add(ack)
    session.commit()
    session.refresh(ack)
    # SQLite drops tzinfo on round-trip even for a `DateTime(timezone=True)`
    # column — normalize back to aware UTC so every caller (the API
    # response, `.isoformat()`, `.astimezone()`) gets an unambiguous
    # instant rather than a naive value later misread as local time.
    ack.acknowledged_at = _as_aware(ack.acknowledged_at)
    return ack


def snooze_item(session: Session, stable_key: str, duration_key: str, now: datetime, tz_name: str | None = None) -> BriefingSnooze:
    """Snoozing accepts only a fixed, server-validated duration key —
    never an arbitrary client-supplied timestamp. Never executes or
    schedules any external action; purely a local suppression window on
    the item's CURRENT fingerprint."""
    if duration_key not in SNOOZE_DURATION_LABELS:
        raise BriefingActionError(f"Unknown snooze duration: {duration_key!r}. Must be one of {tuple(SNOOZE_DURATION_LABELS)}.")
    row = _current_ledger_row(session, stable_key)

    if duration_key == "1h":
        snooze_until = now + timedelta(hours=1)
    elif duration_key == "4h":
        snooze_until = now + timedelta(hours=4)
    elif duration_key == "1w":
        snooze_until = now + timedelta(weeks=1)
    else:  # tomorrow_morning
        try:
            snooze_until = _tomorrow_morning_utc(now, tz_name or DEFAULT_BRIEFING_TIMEZONE)
        except Exception as exc:
            raise BriefingActionError(f"Unknown timezone: {tz_name!r}.") from exc

    # Superseding an existing active snooze on the same fingerprint (e.g.
    # choosing "1 week" after already snoozing "1 hour") restores the old
    # one first, so history shows an explicit trail rather than two
    # simultaneously-active rows for the same concern.
    existing = (
        session.query(BriefingSnooze)
        .filter(
            BriefingSnooze.stable_key == stable_key,
            BriefingSnooze.fingerprint == row.current_fingerprint,
            BriefingSnooze.status == "active",
        )
        .all()
    )
    for old in existing:
        old.status = "restored"
        old.restored_at = now

    snooze = BriefingSnooze(
        stable_key=stable_key,
        fingerprint=row.current_fingerprint,
        duration_key=duration_key,
        status="active",
        title_snapshot=row.last_title,
        subtitle_snapshot=row.last_subtitle,
        domain_slug_snapshot=row.domain_slug,
        link_target_snapshot=row.last_link_target,
        snoozed_at=now,
        snooze_until=snooze_until,
    )
    session.add(snooze)
    session.commit()
    session.refresh(snooze)
    # SQLite drops tzinfo on round-trip even for a `DateTime(timezone=True)`
    # column — normalize back to aware UTC so every caller (the API
    # response, `.isoformat()`, `.astimezone()`) gets an unambiguous
    # instant rather than a naive value later misread as local time.
    snooze.snoozed_at = _as_aware(snooze.snoozed_at)
    snooze.snooze_until = _as_aware(snooze.snooze_until)
    return snooze


def restore_item(session: Session, stable_key: str, now: datetime) -> bool:
    """Clears any active acknowledgement AND any active snooze on the
    item's current fingerprint. Returns True if anything was actually
    restored. This never touches a stale acknowledgement/snooze tied to
    an OLD fingerprint — those are already inert (see `is_suppressed`)."""
    row = _current_ledger_row(session, stable_key)
    restored = False
    acks = (
        session.query(BriefingAcknowledgement)
        .filter(
            BriefingAcknowledgement.stable_key == stable_key,
            BriefingAcknowledgement.fingerprint == row.current_fingerprint,
            BriefingAcknowledgement.status == "active",
        )
        .all()
    )
    for ack in acks:
        ack.status = "restored"
        ack.restored_at = now
        restored = True
    snoozes = (
        session.query(BriefingSnooze)
        .filter(
            BriefingSnooze.stable_key == stable_key,
            BriefingSnooze.fingerprint == row.current_fingerprint,
            BriefingSnooze.status == "active",
        )
        .all()
    )
    for snooze in snoozes:
        snooze.status = "restored"
        snooze.restored_at = now
        restored = True
    session.commit()
    return restored


def _acknowledged_and_snoozed_entries(session: Session, now: datetime) -> list[AcknowledgedOrSnoozedEntry]:
    entries: list[AcknowledgedOrSnoozedEntry] = []
    for ack in session.query(BriefingAcknowledgement).filter(BriefingAcknowledgement.status == "active").all():
        entries.append(
            AcknowledgedOrSnoozedEntry(
                stable_key=ack.stable_key,
                kind="acknowledged",
                title=ack.title_snapshot,
                subtitle=ack.subtitle_snapshot,
                domain_slug=ack.domain_slug_snapshot,
                link_target=ack.link_target_snapshot,
                since=_as_aware(ack.acknowledged_at),
                until=None,
                duration_key=None,
            )
        )
    for snooze in (
        session.query(BriefingSnooze)
        .filter(BriefingSnooze.status == "active", BriefingSnooze.snooze_until > now)
        .all()
    ):
        entries.append(
            AcknowledgedOrSnoozedEntry(
                stable_key=snooze.stable_key,
                kind="snoozed",
                title=snooze.title_snapshot,
                subtitle=snooze.subtitle_snapshot,
                domain_slug=snooze.domain_slug_snapshot,
                link_target=snooze.link_target_snapshot,
                since=_as_aware(snooze.snoozed_at),
                until=_as_aware(snooze.snooze_until),
                duration_key=snooze.duration_key,
            )
        )
    entries.sort(key=lambda e: e.since, reverse=True)
    return entries


def cleanup_old_briefing_state(session: Session, now: datetime) -> int:
    """Startup-time bounded retention sweep (wired into `main.py`'s
    lifespan, alongside the existing due-backup/interrupted-execution/
    stale-export-temp-file sweeps): prunes resolved ledger rows and
    restored/expired acknowledge/snooze rows past their retention window.
    Never touches an 'active' row of any kind. Precise, owned DELETE
    queries — never a broad table truncation."""
    ledger_cutoff = now - timedelta(days=LEDGER_RESOLVED_RETENTION_DAYS)
    ledger_result = session.execute(
        delete(BriefingItemState).where(
            BriefingItemState.status == "resolved", BriefingItemState.last_resolved_at < ledger_cutoff
        )
    )
    ack_snooze_cutoff = now - timedelta(days=ACK_SNOOZE_INACTIVE_RETENTION_DAYS)
    ack_result = session.execute(
        delete(BriefingAcknowledgement).where(
            BriefingAcknowledgement.status == "restored", BriefingAcknowledgement.restored_at < ack_snooze_cutoff
        )
    )
    snooze_result = session.execute(
        delete(BriefingSnooze).where(
            BriefingSnooze.status.in_(("restored", "expired")), BriefingSnooze.snooze_until < ack_snooze_cutoff
        )
    )
    session.commit()
    return (ledger_result.rowcount or 0) + (ack_result.rowcount or 0) + (snooze_result.rowcount or 0)


def assemble_home_briefing(
    session: Session,
    *,
    include_body: bool,
    include_mind: bool,
    include_people: bool,
    now: datetime,
    trigger: str = "home_view",
) -> HomeBriefing:
    """Deterministically assembles the concise Home situational briefing,
    including Phase 12B continuity (new/changed/ongoing/resolved/reopened
    classification, acknowledge/snooze suppression, and a recorded,
    dedup-aware, bounded-history snapshot). No model call, no Hermes
    call — the only writes here are to this module's own presentation-
    state tables (the ledger, the snapshot audit trail); the underlying
    Calendar/task/action/integration/routine/Health data is never
    touched.

    `include_mind`/`include_people` are accepted and stored for parity
    with the Morning Briefing routine's per-domain opt-in shape, but gate
    nothing in this function: no MIND/PEOPLE source is read here at all,
    regardless of their value (see the module docstring)."""
    expire_due_snoozes(session, now)

    candidates, evaluations = _gather_candidates(session, include_body=include_body, now=now)
    # Phase 12C: merge active Mission Focus pins into the SAME candidate
    # set — never a second, parallel priority/state system — before
    # classification runs, so a pinned item is reconciled against the
    # ledger exactly like any other candidate.
    candidates, pin_resolved_info = _gather_mission_focus(session, candidates, now)
    # Classification is computed over the COMPLETE candidate set, before
    # any cap is applied — priority-cap churn must never look like a real
    # change (Phase 12B brief).
    change_states, resolved_items = _reconcile_ledger(session, candidates, evaluations, now)

    visible: list[BriefingItem] = []
    for item in candidates:
        suppression = is_suppressed(session, item.id, item.fingerprint, now)
        if suppression is not None:
            continue
        visible.append(_apply_change_state(item, change_states[item.id]))
    visible.extend(resolved_items)  # already carry change_state="resolved"; never suppressible

    visible = sorted(visible, key=_sort_key)[:HOME_BRIEFING_MAX_ITEMS]

    record_snapshot(
        session,
        consumer="home",
        trigger=trigger,
        item_keys=[(item.id, item.fingerprint) for item in candidates],
        now=now,
    )
    session.commit()

    return HomeBriefing(
        generated_at=now,
        items=visible,
        sources=_source_statuses(session, now),
        include_body=include_body,
        include_mind=include_mind,
        include_people=include_people,
        acknowledged_and_snoozed=_acknowledged_and_snoozed_entries(session, now),
        mission_focus=build_mission_focus_rail(session, change_states, pin_resolved_info, now),
    )


def get_snapshot_history(session: Session, consumer: str, limit: int = 20) -> list[BriefingSnapshot]:
    return (
        session.query(BriefingSnapshot)
        .filter(BriefingSnapshot.consumer == consumer)
        .order_by(BriefingSnapshot.generated_at.desc())
        .limit(limit)
        .all()
    )
