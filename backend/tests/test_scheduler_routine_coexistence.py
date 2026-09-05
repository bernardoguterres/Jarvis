"""Phase 10B: the single scheduler loop drives both Phase 10A integration
resync and Phase 10B routines in the same tick/startup pass, without one
interfering with the other. No real Keychain/Google/Hermes/model call."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app import integration_service
from app.config import Settings
from app.credential_store import FakeCredentialStore
from app.database import build_engine, build_sessionmaker
from app.migration_info import upgrade_database_to_head
from app.models_routines import RoutineRun, RoutineSchedule
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


def test_one_scheduler_loop_runs_both_integration_sync_and_routines(tmp_path) -> None:
    session_factory, engine = _make_session_factory(tmp_path / "install")
    store = FakeCredentialStore()
    with session_factory() as session:
        integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
        store.set("google_calendar", "access_token", "AT1")
        store.set("google_calendar", "refresh_token", "RT1")
        store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
        conn = integration_service.get_connection(session, "google_calendar")
        conn.status = "connected"
        session.commit()

        int_schedule = session.get(IntegrationSyncSchedule, "google_calendar")
        int_schedule.enabled = True
        int_schedule.next_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()

        routine_schedule = session.get(RoutineSchedule, "morning_briefing")
        routine_schedule.enabled = True
        routine_schedule.next_due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": []})

    async def _run():
        runtime = SchedulerRuntime(session_factory, store, httpx.Client(transport=httpx.MockTransport(handler)), tick_interval_seconds=10)
        await runtime.start()  # this runs the startup catch-up pass for both
        await runtime.stop()

    try:
        asyncio.run(_run())
        with session_factory() as session:
            int_runs = session.query(IntegrationSyncRun).filter(IntegrationSyncRun.provider == "google_calendar").count()
            routine_runs = session.query(RoutineRun).filter(RoutineRun.routine_type == "morning_briefing").count()
            assert int_runs == 1
            assert routine_runs == 1

            # Neither schedule's due-time bookkeeping was corrupted by the other running in the same pass.
            int_schedule_after = session.get(IntegrationSyncSchedule, "google_calendar")
            routine_schedule_after = session.get(RoutineSchedule, "morning_briefing")
            assert int_schedule_after.last_status == "ok"
            assert routine_schedule_after.last_status == "ok"
    finally:
        engine.dispose()
