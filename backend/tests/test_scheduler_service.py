"""Phase 10: controller-owned automatic integration resync — the pure
logic layer. Every test uses an injected fake clock and FakeCredentialStore;
none ever touches the real Keychain, a real Google API, Hermes, or makes a
model call. Real HTTP is mocked via httpx.MockTransport exactly like the
existing Phase 9 integration tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app import integration_service, scheduler_service
from app.credential_store import FakeCredentialStore
from app.models_scheduler import IntegrationSyncRun, IntegrationSyncSchedule


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _fixed_clock(t: datetime):
    return lambda: t


def _configure_and_connect_calendar(db_session: Session, store: FakeCredentialStore) -> None:
    integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    conn = integration_service.get_connection(db_session, "google_calendar")
    conn.status = "connected"
    conn.scopes_json = "[]"
    db_session.commit()


def _empty_calendar_handler(request: httpx.Request) -> httpx.Response:
    if "calendarList" in request.url.path:
        return httpx.Response(200, json={"items": []})
    return httpx.Response(200, json={"items": []})


# --- Defaults / configuration ------------------------------------------


def test_schedules_are_disabled_by_default(db_session: Session) -> None:
    schedule = scheduler_service.get_or_create_schedule(db_session, "google_calendar")
    assert schedule.enabled is False
    schedule2 = scheduler_service.get_or_create_schedule(db_session, "google_health")
    assert schedule2.enabled is False


def test_enabling_schedules_an_immediate_first_sync(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = scheduler_service.set_schedule(
        db_session, "google_calendar", enabled=True, interval_minutes=30, clock=_fixed_clock(now)
    )
    assert schedule.enabled is True
    assert schedule.next_due_at.replace(tzinfo=timezone.utc) == now


def test_disabling_clears_next_due_at(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=30, clock=_fixed_clock(now))
    schedule = scheduler_service.set_schedule(db_session, "google_calendar", enabled=False, interval_minutes=30, clock=_fixed_clock(now))
    assert schedule.enabled is False
    assert schedule.next_due_at is None


def test_provider_specific_interval_validation(db_session: Session) -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(scheduler_service.ScheduleValidationError):
        scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=5, clock=_fixed_clock(now))
    with pytest.raises(scheduler_service.ScheduleValidationError):
        scheduler_service.set_schedule(db_session, "google_health", enabled=True, interval_minutes=15, clock=_fixed_clock(now))
    # A valid, provider-specific cadence must not raise.
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=15, clock=_fixed_clock(now))
    scheduler_service.set_schedule(db_session, "google_health", enabled=True, interval_minutes=60, clock=_fixed_clock(now))


# --- Due-time / recurring sync -------------------------------------------


def test_ordinary_recurring_due_sync_advances_next_due_at(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=30, clock=_fixed_clock(t0))

    t1 = t0 + timedelta(minutes=1)
    runs = scheduler_service.tick(db_session, store, _client(_empty_calendar_handler), _fixed_clock(t1))
    assert len(runs) == 1
    assert runs[0].outcome == "succeeded"
    assert runs[0].trigger == "scheduled"

    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    assert schedule.next_due_at.replace(tzinfo=timezone.utc) == t1 + timedelta(minutes=30)
    assert schedule.consecutive_failure_count == 0


def test_not_yet_due_schedule_is_skipped_by_tick(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=30, clock=_fixed_clock(t0))
    # Advance next_due_at into the future manually, as if a sync just ran.
    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    schedule.next_due_at = t0 + timedelta(minutes=30)
    db_session.commit()

    runs = scheduler_service.tick(db_session, store, _client(_empty_calendar_handler), _fixed_clock(t0 + timedelta(minutes=1)))
    assert runs == []


def test_exactly_one_startup_catchup_when_overdue(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = scheduler_service.get_or_create_schedule(db_session, "google_calendar")
    schedule.enabled = True
    schedule.interval_minutes = 30
    schedule.next_due_at = t0 - timedelta(hours=5)  # very overdue
    db_session.commit()

    runs = scheduler_service.startup_catchup(db_session, store, _client(_empty_calendar_handler), _fixed_clock(t0))
    assert len(runs) == 1
    assert runs[0].trigger == "startup_catchup"


def test_no_replay_storm_after_long_downtime(db_session: Session) -> None:
    """Missing many intervals while asleep must produce exactly one catch-up
    sync, never one per missed interval."""
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    schedule = scheduler_service.get_or_create_schedule(db_session, "google_calendar")
    schedule.enabled = True
    schedule.interval_minutes = 15
    schedule.next_due_at = t0 - timedelta(days=3)  # ~288 missed 15-minute intervals
    db_session.commit()

    runs = scheduler_service.startup_catchup(db_session, store, _client(_empty_calendar_handler), _fixed_clock(t0))
    assert len(runs) == 1

    # A second startup_catchup call immediately after must not re-trigger —
    # next_due_at has already advanced from the real completion time.
    runs2 = scheduler_service.startup_catchup(db_session, store, _client(_empty_calendar_handler), _fixed_clock(t0))
    assert runs2 == []


# --- Single-flight / collision handling ----------------------------------


def test_manual_and_scheduled_sync_cannot_overlap(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    acquired = scheduler_service.try_acquire_provider_lock("google_calendar")
    assert acquired is True
    try:
        run = scheduler_service.run_provider_sync(
            db_session, store, _client(_empty_calendar_handler), "google_calendar", "manual", _fixed_clock(t0)
        )
        assert run.outcome == "skipped"
    finally:
        scheduler_service.release_provider_lock("google_calendar")


def test_lock_is_released_after_a_run_so_a_later_sync_can_proceed(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    run1 = scheduler_service.run_provider_sync(db_session, store, _client(_empty_calendar_handler), "google_calendar", "manual", _fixed_clock(t0))
    assert run1.outcome == "succeeded"
    run2 = scheduler_service.run_provider_sync(db_session, store, _client(_empty_calendar_handler), "google_calendar", "manual", _fixed_clock(t0))
    assert run2.outcome == "succeeded"


# --- Failure handling -----------------------------------------------------


def test_failure_increments_backoff_and_does_not_disconnect(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=15, clock=_fixed_clock(t0))

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    run = scheduler_service.run_provider_sync(
        db_session, store, _client(failing_handler), "google_calendar", "scheduled", _fixed_clock(t0)
    )
    assert run.outcome == "failed"
    assert "token" not in (run.reason or "").lower()
    assert "AT1" not in (run.reason or "")

    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    assert schedule.consecutive_failure_count == 1
    assert schedule.last_status == "failed"
    # Backoff: next_due_at is later than a plain +15 minutes would be (2x here).
    assert schedule.next_due_at.replace(tzinfo=timezone.utc) == t0 + timedelta(minutes=30)

    # Real connection status is untouched by a sync failure.
    conn = integration_service.get_connection(db_session, "google_calendar")
    assert conn.status == "connected"


def test_reconnect_required_when_credentials_missing(db_session: Session) -> None:
    store = FakeCredentialStore()  # never configured/connected
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.get_or_create_schedule(db_session, "google_calendar")

    run = scheduler_service.run_provider_sync(
        db_session, store, _client(lambda r: httpx.Response(200)), "google_calendar", "scheduled", _fixed_clock(t0)
    )
    assert run.outcome == "failed"
    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    assert schedule.last_status == "reconnect_required"


def test_backoff_resets_after_success(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_calendar", enabled=True, interval_minutes=15, clock=_fixed_clock(t0))

    scheduler_service.run_provider_sync(db_session, store, _client(lambda r: httpx.Response(500)), "google_calendar", "scheduled", _fixed_clock(t0))
    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    assert schedule.consecutive_failure_count == 1

    scheduler_service.run_provider_sync(db_session, store, _client(_empty_calendar_handler), "google_calendar", "scheduled", _fixed_clock(t0))
    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    assert schedule.consecutive_failure_count == 0
    assert schedule.last_status == "ok"


def test_retry_after_is_respected_over_computed_backoff(db_session: Session) -> None:
    store = FakeCredentialStore()
    integration_service.store_client_credentials(store, "google_health", client_id="cid", client_secret="csecret")
    # Force a token refresh (expired) that then hits a 429 with Retry-After.
    store.set("google_health", "access_token", "OLD")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat())
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.set_schedule(db_session, "google_health", enabled=True, interval_minutes=60, clock=_fixed_clock(t0))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7200"})  # 2 hours, longer than the 60-min interval

    run = scheduler_service.run_provider_sync(db_session, store, _client(handler), "google_health", "scheduled", _fixed_clock(t0))
    assert run.outcome == "failed"
    schedule = db_session.get(IntegrationSyncSchedule, "google_health")
    # Retry-After (120 min) wins over the plain 2x-interval backoff (120 min would tie here,
    # but a longer Retry-After must always win) — assert it's honored, not undershot.
    assert schedule.next_due_at.replace(tzinfo=timezone.utc) >= t0 + timedelta(minutes=120)


def test_google_health_partial_status_is_preserved_truthfully(db_session: Session) -> None:
    store = FakeCredentialStore()
    integration_service.store_client_credentials(store, "google_health", client_id="cid", client_secret="csecret")
    store.set("google_health", "access_token", "AT1")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(500)
        if "dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": []})
        return httpx.Response(200, json={"dataPoints": []})

    run = scheduler_service.run_provider_sync(db_session, store, _client(handler), "google_health", "scheduled", _fixed_clock(t0))
    assert run.outcome == "partial"
    schedule = db_session.get(IntegrationSyncSchedule, "google_health")
    assert schedule.last_status == "partial"
    assert schedule.consecutive_failure_count == 0  # a partial sync is not a hard failure


# --- Auditability / retention ----------------------------------------------


def test_bounded_history_retention(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    from app.models_scheduler import SYNC_RUN_RETENTION_PER_PROVIDER

    for i in range(SYNC_RUN_RETENTION_PER_PROVIDER + 10):
        scheduler_service.run_provider_sync(
            db_session, store, _client(_empty_calendar_handler), "google_calendar", "manual", _fixed_clock(t0 + timedelta(minutes=i))
        )

    count = db_session.query(IntegrationSyncRun).filter(IntegrationSyncRun.provider == "google_calendar").count()
    assert count == SYNC_RUN_RETENTION_PER_PROVIDER


def test_sync_run_never_stores_raw_provider_response_or_secrets(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure_and_connect_calendar(db_session, store)
    t0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    scheduler_service.run_provider_sync(db_session, store, _client(_empty_calendar_handler), "google_calendar", "manual", _fixed_clock(t0))

    run = db_session.query(IntegrationSyncRun).filter(IntegrationSyncRun.provider == "google_calendar").one()
    assert "AT1" not in (run.result_summary_json or "")
    assert "RT1" not in (run.result_summary_json or "")
    summary = json.loads(run.result_summary_json)
    assert isinstance(summary.get("cached_events"), int)
