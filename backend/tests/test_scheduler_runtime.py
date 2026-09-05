"""Phase 10: the background loop wrapper itself. Uses a fake credential
store and a mocked httpx client — no real Keychain, Google API, Hermes, or
model call. Verifies the one-instance/no-duplicate-loop and clean-shutdown
guarantees; the actual sync logic is covered by test_scheduler_service.py.

No async test plugin (pytest-asyncio et al.) is installed in this project,
so each test drives its own event loop directly via `asyncio.run()` rather
than adding a new dependency for three tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app import integration_service
from app.config import Settings
from app.credential_store import FakeCredentialStore
from app.database import build_engine, build_sessionmaker
from app.migration_info import upgrade_database_to_head
from app.models_scheduler import IntegrationSyncRun, IntegrationSyncSchedule
from app.scheduler_runtime import SchedulerRuntime
from app.seed import seed_domains


def _make_session_factory(tmp_path):
    settings = Settings(jarvis_data_dir=str(tmp_path))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    engine = build_engine(settings.database_url)
    session_factory = build_sessionmaker(engine)
    with session_factory() as session:
        seed_domains(session)
    return session_factory, engine


def test_start_is_idempotent_no_duplicate_loop(tmp_path) -> None:
    async def _run():
        session_factory, engine = _make_session_factory(tmp_path / "install")
        try:
            runtime = SchedulerRuntime(
                session_factory,
                FakeCredentialStore(),
                httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))),
                tick_interval_seconds=0.05,
            )
            await runtime.start()
            first_task = runtime._task
            await runtime.start()  # a second call must not create a second task
            assert runtime._task is first_task
            await runtime.stop()
        finally:
            engine.dispose()

    asyncio.run(_run())


def test_stop_is_clean_and_bounded(tmp_path) -> None:
    async def _run():
        session_factory, engine = _make_session_factory(tmp_path / "install")
        try:
            runtime = SchedulerRuntime(
                session_factory,
                FakeCredentialStore(),
                httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": []}))),
                tick_interval_seconds=0.05,
            )
            await runtime.start()
            await asyncio.wait_for(runtime.stop(), timeout=2.0)
            assert runtime._task is None
            await runtime.stop()  # stopping an already-stopped runtime must not raise
        finally:
            engine.dispose()

    asyncio.run(_run())


def test_rapid_restart_does_not_duplicate_a_sync(tmp_path) -> None:
    """Simulates two quick restarts in a row: startup catch-up must run at
    most once per overdue provider each time, never stacking up extra
    syncs merely because the process restarted quickly."""
    install_dir = tmp_path / "install"
    session_factory, engine = _make_session_factory(install_dir)
    with session_factory() as session:
        store = FakeCredentialStore()
        integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
        store.set("google_calendar", "access_token", "AT1")
        store.set("google_calendar", "refresh_token", "RT1")
        store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        conn = integration_service.get_connection(session, "google_calendar")
        conn.status = "connected"
        session.commit()

        schedule = session.get(IntegrationSyncSchedule, "google_calendar")
        schedule.enabled = True
        schedule.next_due_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()
    engine.dispose()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    store = FakeCredentialStore()
    integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    async def _restart_once():
        session_factory_n, engine_n = _make_session_factory(install_dir)
        runtime = SchedulerRuntime(session_factory_n, store, httpx.Client(transport=httpx.MockTransport(handler)), tick_interval_seconds=10)
        await runtime.start()
        await runtime.stop()
        with session_factory_n() as session:
            count = session.query(IntegrationSyncRun).filter(IntegrationSyncRun.provider == "google_calendar").count()
        engine_n.dispose()
        return count

    run_count_after_first = asyncio.run(_restart_once())
    assert run_count_after_first == 1

    # Second quick "restart" immediately after — next_due_at has already
    # advanced from the first run's real completion time, so no new sync
    # should fire even though the process restarted again right away.
    run_count_after_second = asyncio.run(_restart_once())
    assert run_count_after_second == 1
