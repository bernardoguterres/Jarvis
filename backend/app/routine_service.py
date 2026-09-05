"""Phase 10B: controller-owned proactive routines — the testable logic
layer. Mirrors app/scheduler_service.py's patterns exactly (injected
clock, per-type single-flight lock, bounded exponential backoff, no-replay
catch-up semantics) so the same scheduler loop can drive both Phase 10A
integration resync and Phase 10B routines without duplicating that
machinery.

A routine never creates an action proposal, mutates Calendar, writes
Health data, edits a memory, sends a notification, speaks aloud, or
contacts anyone — it only assembles a deterministic, source-referenced
summary from already-locally-cached data. No model call happens here;
the separate, explicit "Discuss with Jarvis" action (app/routers/routines.py)
is the only path that ever reaches a model, and only when Bernardo asks
for it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.briefing_service import domain_id_by_slug as _domain_id_by_slug
from app.briefing_service import latest_google_health_summary, open_records, record_snapshot, todays_calendar_events
from app.models_integrations import GoogleHealthDailySummary
from app.models_memory import StructuredRecord
from app.models_routines import (
    ALL_DOMAIN_SLUGS,
    ROUTINE_RUN_RETENTION_PER_TYPE,
    RoutineRun,
    RoutineSchedule,
)
from app.recall_index_service import sync_recall

Clock = Callable[[], datetime]

_BACKOFF_MULTIPLIER_CAP = 8
_BACKOFF_ABSOLUTE_CAP_MINUTES = 24 * 60
_RETRY_INTERVAL_MINUTES = 60  # base unit for routine backoff (routines are daily/weekly, not minute-cadence)

_ROUTINE_LOCKS: dict[str, threading.Lock] = {
    "morning_briefing": threading.Lock(),
    "evening_checkin": threading.Lock(),
    "weekly_review": threading.Lock(),
}


class RoutineValidationError(Exception):
    pass


def try_acquire_routine_lock(routine_type: str) -> bool:
    return _ROUTINE_LOCKS[routine_type].acquire(blocking=False)


def release_routine_lock(routine_type: str) -> None:
    _ROUTINE_LOCKS[routine_type].release()


# --------------------------------------------------------------------------
# Schedule configuration
# --------------------------------------------------------------------------


def validate_local_time(local_time: str) -> None:
    try:
        hh, mm = local_time.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        raise RoutineValidationError(f"local_time must be HH:MM (24-hour), got {local_time!r}.") from None


def validate_domains(routine_type: str, selected_domains: list[str]) -> None:
    for slug in selected_domains:
        if slug not in ALL_DOMAIN_SLUGS:
            raise RoutineValidationError(f"Unknown domain slug: {slug!r}.")


def get_or_create_schedule(session: Session, routine_type: str) -> RoutineSchedule:
    schedule = session.get(RoutineSchedule, routine_type)
    if schedule is None:
        defaults = {
            "morning_briefing": ("08:00", None),
            "evening_checkin": ("20:00", None),
            "weekly_review": ("09:00", 6),
        }
        local_time, weekday = defaults[routine_type]
        schedule = RoutineSchedule(
            routine_type=routine_type, enabled=False, local_time=local_time, weekday=weekday, timezone="UTC"
        )
        session.add(schedule)
        session.flush()
    return schedule


def _next_occurrence_utc(now_utc: datetime, local_time: str, tz_name: str, weekday: int | None) -> datetime:
    """Computes the next wall-clock occurrence of `local_time` (and, for a
    weekly routine, `weekday`) in `tz_name`, correctly handling DST by
    constructing the datetime directly in local wall-clock terms (never by
    adding a fixed-offset timedelta to a UTC time) and letting `zoneinfo`
    resolve the actual UTC offset for that specific local moment."""
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    hh, mm = (int(p) for p in local_time.split(":"))

    candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if weekday is not None:
        days_ahead = (weekday - candidate.weekday()) % 7
        candidate = candidate + timedelta(days=days_ahead)
        if candidate <= now_local:
            candidate = candidate + timedelta(days=7)
    else:
        if candidate <= now_local:
            candidate = candidate + timedelta(days=1)

    return candidate.astimezone(timezone.utc)


def set_schedule(
    session: Session,
    routine_type: str,
    *,
    enabled: bool,
    local_time: str,
    timezone_name: str,
    weekday: int | None,
    selected_domains: list[str],
    clock: Clock,
) -> RoutineSchedule:
    """Explicit local UI action — configuring Jarvis's own routine
    schedule/domain-selection metadata has no external side effect, so
    this does not go through the Phase 8 proposal lifecycle."""
    validate_local_time(local_time)
    validate_domains(routine_type, selected_domains)
    if routine_type == "weekly_review" and weekday is None:
        weekday = 6
    if routine_type != "weekly_review":
        weekday = None
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise RoutineValidationError(f"Unknown timezone: {timezone_name!r}.") from exc

    schedule = get_or_create_schedule(session, routine_type)
    schedule.enabled = enabled
    schedule.local_time = local_time
    schedule.timezone = timezone_name
    schedule.weekday = weekday
    schedule.selected_domains_json = json.dumps(selected_domains)
    now = clock()
    schedule.next_due_at = _next_occurrence_utc(now, local_time, timezone_name, weekday) if enabled else None
    session.commit()
    session.refresh(schedule)
    return schedule


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _backoff_minutes(consecutive_failure_count: int) -> int:
    multiplier = min(2**consecutive_failure_count, _BACKOFF_MULTIPLIER_CAP)
    return min(_RETRY_INTERVAL_MINUTES * multiplier, _BACKOFF_ABSOLUTE_CAP_MINUTES)


# --------------------------------------------------------------------------
# Content assembly — deterministic, source-referenced, no model call
# --------------------------------------------------------------------------


@dataclass
class OutputLine:
    text: str
    source_ref: str | None = None


@dataclass
class OutputSection:
    title: str
    lines: list[OutputLine] = field(default_factory=list)


def _record_payload(record: StructuredRecord) -> dict:
    try:
        return json.loads(record.payload_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _life_tasks_section(session: Session, life_domain_id: str) -> OutputSection:
    rows = open_records(session, life_domain_id, "life_task")
    lines = []
    for r in rows:
        payload = _record_payload(r)
        title = payload.get("title", "(untitled task)")
        due = f" (due {payload['due_date']})" if payload.get("due_date") else ""
        lines.append(OutputLine(text=f"{title}{due}", source_ref=f"record:{r.id[:8]}"))
    return OutputSection(title="Active LIFE tasks", lines=lines)


def _calendar_section(session: Session, today: date_type) -> OutputSection:
    rows = todays_calendar_events(session, today)
    lines = []
    for ev in rows:
        when = ev.start_datetime.strftime("%H:%M") if ev.start_datetime else "all day"
        lines.append(OutputLine(text=f"{when} — {ev.title}", source_ref=f"calendar_event:{ev.id[:8]}"))
    return OutputSection(title="Today's Calendar events", lines=lines)


def _path_deadlines_section(session: Session, path_domain_id: str) -> OutputSection:
    rows = open_records(session, path_domain_id, "path_deadline")
    lines = []
    for r in rows:
        payload = _record_payload(r)
        title = payload.get("title", "(untitled deadline)")
        due = f" (due {payload['due_date']})" if payload.get("due_date") else ""
        lines.append(OutputLine(text=f"{title}{due}", source_ref=f"record:{r.id[:8]}"))
    return OutputSection(title="Upcoming PATH deadlines", lines=lines)


def _build_checkpoints_section(session: Session, build_domain_id: str) -> OutputSection:
    rows = open_records(session, build_domain_id, "build_checkpoint")
    lines = []
    for r in rows:
        payload = _record_payload(r)
        text = f"{payload.get('project', '(project)')}: {payload.get('summary', '')}"
        lines.append(OutputLine(text=text, source_ref=f"record:{r.id[:8]}"))
    return OutputSection(title="Active BUILD checkpoints", lines=lines)


def _body_section(session: Session) -> OutputSection:
    row = latest_google_health_summary(session)
    lines = []
    if row is not None:
        parts = []
        if row.steps is not None:
            parts.append(f"steps={row.steps}")
        if row.sleep_minutes_asleep is not None:
            parts.append(f"sleep_min={row.sleep_minutes_asleep}")
        if row.resting_heart_rate is not None:
            parts.append(f"resting_hr={row.resting_heart_rate}")
        if parts:
            lines.append(OutputLine(text=f"{row.date.isoformat()}: " + " ".join(parts), source_ref=f"google_health_summary:{row.id[:8]}"))
    return OutputSection(title="BODY — recent Google Health data", lines=lines)


def _mind_section(session: Session, mind_domain_id: str) -> OutputSection:
    rows = (
        session.query(StructuredRecord)
        .filter(StructuredRecord.domain_id == mind_domain_id, StructuredRecord.record_type == "mind_checkin")
        .order_by(StructuredRecord.created_at.desc())
        .limit(5)
        .all()
    )
    lines = [
        OutputLine(text=f"mood={_record_payload(r).get('mood', '?')}", source_ref=f"record:{r.id[:8]}") for r in rows
    ]
    return OutputSection(title="MIND — recent check-ins", lines=lines)


def _people_section(session: Session, people_domain_id: str) -> OutputSection:
    rows = (
        session.query(StructuredRecord)
        .filter(StructuredRecord.domain_id == people_domain_id, StructuredRecord.record_type == "people_interaction")
        .order_by(StructuredRecord.created_at.desc())
        .limit(5)
        .all()
    )
    lines = [
        OutputLine(text=f"{_record_payload(r).get('person', '?')}: {_record_payload(r).get('note', '')}", source_ref=f"record:{r.id[:8]}")
        for r in rows
    ]
    return OutputSection(title="PEOPLE — recent interactions", lines=lines)


def build_morning_briefing(session: Session, selected_domains: list[str], today: date_type) -> list[OutputSection]:
    sections = [_calendar_section(session, today)]
    if (life_id := _domain_id_by_slug(session, "life")) is not None:
        sections.append(_life_tasks_section(session, life_id))
    if (path_id := _domain_id_by_slug(session, "path")) is not None:
        sections.append(_path_deadlines_section(session, path_id))
    if (build_id := _domain_id_by_slug(session, "build")) is not None:
        sections.append(_build_checkpoints_section(session, build_id))
    # Sensitive domains: only included on explicit per-routine opt-in.
    if "body" in selected_domains:
        sections.append(_body_section(session))
    if "mind" in selected_domains and (mind_id := _domain_id_by_slug(session, "mind")) is not None:
        sections.append(_mind_section(session, mind_id))
    if "people" in selected_domains and (people_id := _domain_id_by_slug(session, "people")) is not None:
        sections.append(_people_section(session, people_id))
    return sections


_EVENING_CHECKIN_PROMPTS = (
    "What did you get done today?",
    "How are you feeling right now?",
    "Anything notable happen today?",
    "What's tomorrow's top priority?",
)


def build_evening_checkin() -> list[OutputSection]:
    """A fixed, static template — no data pulled, no model call. Bernardo's
    own typed answers (if any) are recorded separately on the run's
    `responses_json`, never auto-promoted to permanent memory."""
    return [OutputSection(title="Evening check-in", lines=[OutputLine(text=p) for p in _EVENING_CHECKIN_PROMPTS])]


def build_weekly_review(session: Session, selected_domains: list[str], today: date_type) -> list[OutputSection]:
    sections: list[OutputSection] = []
    week_ago = today - timedelta(days=7)
    for slug in selected_domains:
        domain_id = _domain_id_by_slug(session, slug)
        if domain_id is None:
            continue
        completed = (
            session.query(StructuredRecord)
            .filter(StructuredRecord.domain_id == domain_id, StructuredRecord.archived_at.isnot(None))
            .order_by(StructuredRecord.archived_at.desc())
            .limit(10)
            .all()
        )
        open_records = (
            session.query(StructuredRecord)
            .filter(StructuredRecord.domain_id == domain_id, StructuredRecord.archived_at.is_(None))
            .order_by(StructuredRecord.created_at.desc())
            .limit(10)
            .all()
        )
        lines = []
        for r in completed:
            payload = _record_payload(r)
            summary = payload.get("title") or payload.get("summary") or payload.get("note") or r.record_type
            lines.append(OutputLine(text=f"Completed: {summary}", source_ref=f"record:{r.id[:8]}"))
        for r in open_records:
            payload = _record_payload(r)
            summary = payload.get("title") or payload.get("summary") or payload.get("note") or r.record_type
            lines.append(OutputLine(text=f"Open: {summary}", source_ref=f"record:{r.id[:8]}"))
        sections.append(OutputSection(title=f"{slug.upper()} — weekly review", lines=lines))

    if "body" in selected_domains:
        rows = (
            session.query(GoogleHealthDailySummary)
            .filter(GoogleHealthDailySummary.date >= week_ago)
            .order_by(GoogleHealthDailySummary.date.desc())
            .all()
        )
        lines = [
            OutputLine(text=f"{r.date.isoformat()}: steps={r.steps}", source_ref=f"google_health_summary:{r.id[:8]}")
            for r in rows
            if r.steps is not None
        ]
        sections.append(OutputSection(title="BODY — Health trends this week", lines=lines))
    return sections


def _sections_to_json(sections: list[OutputSection]) -> str:
    return json.dumps(
        {"sections": [{"title": s.title, "lines": [{"text": ln.text, "source_ref": ln.source_ref} for ln in s.lines]} for s in sections]}
    )


# --------------------------------------------------------------------------
# Execution / scheduling
# --------------------------------------------------------------------------


def _trim_history(session: Session, routine_type: str) -> None:
    session.flush()  # this project's sessions have autoflush=False
    all_ids = list(
        session.execute(
            select(RoutineRun.id).where(RoutineRun.routine_type == routine_type).order_by(RoutineRun.started_at.desc())
        )
        .scalars()
        .all()
    )
    stale_ids = all_ids[ROUTINE_RUN_RETENTION_PER_TYPE:]
    if stale_ids:
        session.execute(delete(RoutineRun).where(RoutineRun.id.in_(stale_ids)))


def run_routine(session: Session, routine_type: str, trigger: str, clock: Clock) -> RoutineRun:
    """Runs one routine execution, guarded by this routine's single-flight
    lock (manual, scheduled, and startup-catchup share it, exactly like
    Phase 10A's integration locks). Never raises — every failure is caught
    and recorded as a sanitized, bounded local audit row. Never creates an
    action proposal, mutates Calendar/Health data, edits a memory, sends a
    notification, or makes a model call."""
    started_at = clock()
    if not try_acquire_routine_lock(routine_type):
        run = RoutineRun(
            routine_type=routine_type,
            trigger=trigger,
            started_at=started_at,
            completed_at=clock(),
            outcome="skipped",
            reason="Another run of this routine is already in progress.",
            selected_domains_json="[]",
        )
        session.add(run)
        _trim_history(session, routine_type)
        session.commit()
        return run
    try:
        schedule = get_or_create_schedule(session, routine_type)
        try:
            selected_domains = json.loads(schedule.selected_domains_json)
        except (json.JSONDecodeError, TypeError):
            selected_domains = []
        today = clock().astimezone(ZoneInfo(schedule.timezone)).date()

        try:
            if routine_type == "morning_briefing":
                sections = build_morning_briefing(session, selected_domains, today)
            elif routine_type == "evening_checkin":
                sections = build_evening_checkin()
            else:
                sections = build_weekly_review(session, selected_domains, today)
            outcome, reason = "succeeded", None
        except Exception as exc:  # never let a routine crash the scheduler
            sections = []
            outcome, reason = "failed", f"unexpected error: {type(exc).__name__}"

        now = clock()

        # Phase 12B: a lightweight audit-only snapshot, recorded ONLY for
        # Morning Briefing and ONLY under its own "morning_briefing"
        # baseline — this never touches BriefingItemState (the Home-only
        # continuity ledger) or any acknowledge/snooze table, so a
        # background routine run can never silently consume Home's "new
        # since you last opened Jarvis" comparison baseline. No per-item
        # fingerprinting is needed here since nothing reads this back for
        # change-state display; the digest is derived straight from the
        # routine's own rendered line text.
        if routine_type == "morning_briefing" and outcome == "succeeded":
            record_snapshot(
                session,
                consumer="morning_briefing",
                trigger=f"morning_briefing_{trigger}",
                item_keys=[
                    (line.source_ref or f"{section.title}:{i}", line.text)
                    for section in sections
                    for i, line in enumerate(section.lines)
                ],
                now=now,
            )
        run = RoutineRun(
            routine_type=routine_type,
            trigger=trigger,
            started_at=started_at,
            completed_at=now,
            outcome=outcome,
            reason=reason,
            output_json=_sections_to_json(sections) if outcome == "succeeded" else None,
            selected_domains_json=json.dumps(selected_domains),
        )
        session.add(run)
        session.flush()
        sync_recall(session, "routine_run", run.id)

        schedule.last_run_at = now
        if outcome == "succeeded":
            schedule.last_status = "ok"
            schedule.last_error = None
            schedule.consecutive_failure_count = 0
            if schedule.enabled:
                schedule.next_due_at = _next_occurrence_utc(now, schedule.local_time, schedule.timezone, schedule.weekday)
        else:
            schedule.consecutive_failure_count += 1
            schedule.last_status = "failed"
            schedule.last_error = reason
            if schedule.enabled:
                schedule.next_due_at = now + timedelta(minutes=_backoff_minutes(schedule.consecutive_failure_count))

        _trim_history(session, routine_type)
        session.commit()
        return run
    finally:
        release_routine_lock(routine_type)


def startup_catchup(session: Session, clock: Clock) -> list[RoutineRun]:
    """At most one catch-up run per overdue, enabled routine."""
    now = clock()
    runs = []
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        schedule = session.get(RoutineSchedule, routine_type)
        if schedule is None or not schedule.enabled or schedule.next_due_at is None:
            continue
        if _as_aware(schedule.next_due_at) <= now:
            runs.append(run_routine(session, routine_type, "startup_catchup", clock))
    return runs


def tick(session: Session, clock: Clock) -> list[RoutineRun]:
    now = clock()
    runs = []
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        schedule = session.get(RoutineSchedule, routine_type)
        if schedule is None or not schedule.enabled or schedule.next_due_at is None:
            continue
        if _as_aware(schedule.next_due_at) <= now:
            runs.append(run_routine(session, routine_type, "scheduled", clock))
    return runs
