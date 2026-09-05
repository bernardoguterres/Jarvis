"""Phase 10: controller-owned automatic integration resync — the testable
logic layer. No Hermes cron, no Hermes skill, no sub-agent, no model call:
this is plain Python or/orchestrating the existing Phase 9 sync services
(app/integration_service.py), driven by a background loop
(app/scheduler_runtime.py) started/stopped by FastAPI's own lifespan.

Every function here takes an injected `clock` (a zero-arg callable
returning the current `datetime`) so tests are fully deterministic — never
`datetime.now()` called directly in this module.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import integration_service
from app.credential_store import CredentialStore
from app.models_scheduler import (
    ALLOWED_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    SYNC_RUN_RETENTION_PER_PROVIDER,
    IntegrationSyncRun,
    IntegrationSyncSchedule,
)

Clock = Callable[[], datetime]

# Bounded exponential backoff: interval * 2^failures, capped at 8x the
# configured interval and at an absolute 24 hours — a persistently broken
# provider must never be retried more often than its base cadence, nor so
# rarely that it takes days to notice a fix.
_BACKOFF_MULTIPLIER_CAP = 8
_BACKOFF_ABSOLUTE_CAP_MINUTES = 24 * 60

# One lock per schedulable provider, shared by manual ("Sync now") and
# scheduled/catch-up syncs alike — the single-flight mechanism that makes
# "manual and automatic syncs cannot overlap" true regardless of which
# code path acquires it first.
_PROVIDER_LOCKS: dict[str, threading.Lock] = {
    "google_calendar": threading.Lock(),
    "google_health": threading.Lock(),
}


class ScheduleValidationError(Exception):
    pass


def try_acquire_provider_lock(provider: str) -> bool:
    return _PROVIDER_LOCKS[provider].acquire(blocking=False)


def release_provider_lock(provider: str) -> None:
    _PROVIDER_LOCKS[provider].release()


def validate_interval_minutes(provider: str, interval_minutes: int) -> None:
    allowed = ALLOWED_INTERVAL_MINUTES[provider]
    minimum = MIN_INTERVAL_MINUTES[provider]
    if interval_minutes < minimum:
        raise ScheduleValidationError(
            f"{provider} automatic sync cannot run more often than every {minimum} minutes."
        )
    if interval_minutes not in allowed:
        raise ScheduleValidationError(
            f"{provider} interval must be one of {allowed} minutes, got {interval_minutes}."
        )


def get_or_create_schedule(session: Session, provider: str) -> IntegrationSyncSchedule:
    schedule = session.get(IntegrationSyncSchedule, provider)
    if schedule is None:
        from app.models_scheduler import DEFAULT_INTERVAL_MINUTES

        schedule = IntegrationSyncSchedule(
            provider=provider, enabled=False, interval_minutes=DEFAULT_INTERVAL_MINUTES[provider]
        )
        session.add(schedule)
        session.flush()
    return schedule


def set_schedule(
    session: Session, provider: str, *, enabled: bool, interval_minutes: int, clock: Clock
) -> IntegrationSyncSchedule:
    """Explicit local UI action (not a Phase 8 proposal — see
    docs/DECISIONS.md): Bernardo directly configuring how Jarvis manages
    its own local schedule metadata, with no external side effect of its
    own. Enabling (from disabled, or re-saving while already enabled)
    schedules an immediate first sync; disabling clears the due time so no
    further automatic sync is scheduled."""
    validate_interval_minutes(provider, interval_minutes)
    schedule = get_or_create_schedule(session, provider)
    schedule.interval_minutes = interval_minutes
    schedule.enabled = enabled
    schedule.next_due_at = clock() if enabled else None
    session.commit()
    session.refresh(schedule)
    return schedule


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite silently drops the UTC offset on a `DateTime(timezone=True)`
    column when read back (docs/DECISIONS.md D51) — every comparison
    against a stored due-time must re-attach it before comparing to an
    aware `clock()` value, or a naive/aware comparison raises TypeError."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _backoff_minutes(interval_minutes: int, consecutive_failure_count: int) -> int:
    multiplier = min(2**consecutive_failure_count, _BACKOFF_MULTIPLIER_CAP)
    return min(interval_minutes * multiplier, _BACKOFF_ABSOLUTE_CAP_MINUTES)


def _trim_history(session: Session, provider: str) -> None:
    """Keeps only the most recent SYNC_RUN_RETENTION_PER_PROVIDER runs for
    this provider — a bounded local audit trail, never an unbounded log.
    Fetches all ids ordered newest-first and slices in Python rather than
    an SQL OFFSET-without-LIMIT (SQLite's handling of a bare OFFSET is not
    reliably portable across SQLAlchemy versions)."""
    session.flush()  # this project's sessions have autoflush=False — the
    # just-added run row must be visible to this query, or trimming lags
    # by exactly one row forever.
    all_ids = list(
        session.execute(
            select(IntegrationSyncRun.id)
            .where(IntegrationSyncRun.provider == provider)
            .order_by(IntegrationSyncRun.started_at.desc())
        )
        .scalars()
        .all()
    )
    stale_ids = all_ids[SYNC_RUN_RETENTION_PER_PROVIDER:]
    if stale_ids:
        session.execute(delete(IntegrationSyncRun).where(IntegrationSyncRun.id.in_(stale_ids)))


@dataclass
class SyncAttemptResult:
    outcome: str  # succeeded | partial | failed | skipped
    reason: str | None
    result_summary: dict
    requires_reconnect: bool = False
    retry_after_seconds: int | None = None


def _record_result(
    session: Session, provider: str, trigger: str, clock: Clock, started_at: datetime, result: SyncAttemptResult
) -> IntegrationSyncRun:
    now = clock()
    run = IntegrationSyncRun(
        provider=provider,
        trigger=trigger,
        started_at=started_at,
        completed_at=now,
        outcome=result.outcome,
        reason=result.reason[:500] if result.reason else None,
        result_summary_json=json.dumps(result.result_summary),
    )
    session.add(run)

    if result.outcome != "skipped":
        schedule = get_or_create_schedule(session, provider)
        schedule.last_attempt_at = now
        if result.outcome in ("succeeded", "partial"):
            schedule.last_success_at = now
            schedule.last_status = "ok" if result.outcome == "succeeded" else "partial"
            schedule.last_error = result.reason[:500] if result.reason else None
            schedule.consecutive_failure_count = 0
            if schedule.enabled:
                schedule.next_due_at = now + timedelta(minutes=schedule.interval_minutes)
        else:  # failed
            schedule.consecutive_failure_count += 1
            schedule.last_status = "reconnect_required" if result.requires_reconnect else "failed"
            schedule.last_error = result.reason[:500] if result.reason else None
            if schedule.enabled:
                backoff = _backoff_minutes(schedule.interval_minutes, schedule.consecutive_failure_count)
                if result.retry_after_seconds:
                    # Respect the provider's own Retry-After over our
                    # computed backoff, whichever asks for the longer wait.
                    backoff = max(backoff, -(-result.retry_after_seconds // 60))  # ceil division to minutes
                schedule.next_due_at = now + timedelta(minutes=backoff)

    _trim_history(session, provider)
    session.commit()
    return run


_RECONNECT_ERROR_CODES = {"disconnected", "not_configured"}


def run_provider_sync(
    session: Session,
    store: CredentialStore,
    http_client: httpx.Client,
    provider: str,
    trigger: str,
    clock: Clock,
    *,
    days_back: int | None = None,
) -> IntegrationSyncRun:
    """Runs one sync attempt for `provider`, reusing the existing Phase 9
    sync services (never duplicating provider logic), guarded by this
    provider's single-flight lock so a manual and a scheduled/catch-up sync
    can never run concurrently. Never raises — every failure mode is
    caught and recorded as a sanitized, bounded local audit row."""
    started_at = clock()
    if not try_acquire_provider_lock(provider):
        return _record_result(
            session,
            provider,
            trigger,
            clock,
            started_at,
            SyncAttemptResult(outcome="skipped", reason="Another sync for this provider is already in progress.", result_summary={}),
        )
    try:
        try:
            if provider == "google_calendar":
                conn = integration_service.sync_google_calendar(session, store, http_client)
                from app.models_integrations import CalendarEventCache

                count = session.query(CalendarEventCache).count()
                result = SyncAttemptResult(outcome="succeeded", reason=None, result_summary={"cached_events": count})
            else:
                kwargs = {"days_back": days_back} if days_back is not None else {}
                conn = integration_service.sync_google_health(session, store, http_client, **kwargs)
                from app.models_integrations import GoogleHealthDailySummary, GoogleHealthSession

                summaries = session.query(GoogleHealthDailySummary).count()
                sessions_count = session.query(GoogleHealthSession).count()
                if conn.last_sync_status == "partial":
                    result = SyncAttemptResult(
                        outcome="partial",
                        reason=conn.last_error,
                        result_summary={"daily_summaries": summaries, "sessions": sessions_count},
                    )
                else:
                    result = SyncAttemptResult(
                        outcome="succeeded",
                        reason=None,
                        result_summary={"daily_summaries": summaries, "sessions": sessions_count},
                    )
        except integration_service.IntegrationError as exc:
            requires_reconnect = exc.code in _RECONNECT_ERROR_CODES
            result = SyncAttemptResult(
                outcome="failed",
                reason=f"{exc.code}: {exc.summary}"[:500],
                result_summary={},
                requires_reconnect=requires_reconnect,
                retry_after_seconds=getattr(exc, "retry_after", None),
            )
        except Exception as exc:  # never let a sync attempt crash the scheduler
            result = SyncAttemptResult(outcome="failed", reason=f"unexpected error: {type(exc).__name__}", result_summary={})
        return _record_result(session, provider, trigger, clock, started_at, result)
    finally:
        release_provider_lock(provider)


def startup_catchup(
    session: Session, store: CredentialStore, http_client: httpx.Client, clock: Clock
) -> list[IntegrationSyncRun]:
    """At most one catch-up sync per overdue, enabled provider — never a
    replay of every missed interval. Safe to call every startup: a
    provider that isn't due yet is simply skipped."""
    now = clock()
    runs = []
    for provider in ("google_calendar", "google_health"):
        schedule = session.get(IntegrationSyncSchedule, provider)
        if schedule is None or not schedule.enabled or schedule.next_due_at is None:
            continue
        if _as_aware(schedule.next_due_at) <= now:
            runs.append(run_provider_sync(session, store, http_client, provider, "startup_catchup", clock))
    return runs


def tick(session: Session, store: CredentialStore, http_client: httpx.Client, clock: Clock) -> list[IntegrationSyncRun]:
    """One scheduler tick: run any enabled, due provider exactly once.
    `next_due_at` always advances from the actual completion time of this
    attempt (success or backoff), never by incrementally replaying missed
    slots — this is what structurally prevents a catch-up storm after a
    long sleep/downtime."""
    now = clock()
    runs = []
    for provider in ("google_calendar", "google_health"):
        schedule = session.get(IntegrationSyncSchedule, provider)
        if schedule is None or not schedule.enabled or schedule.next_due_at is None:
            continue
        if _as_aware(schedule.next_due_at) <= now:
            runs.append(run_provider_sync(session, store, http_client, provider, "scheduled", clock))
    return runs
