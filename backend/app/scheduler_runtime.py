"""Phase 10: the actual background loop — a single asyncio task started
and stopped by FastAPI's lifespan (app/main.py), never a Hermes cron job,
never a sub-agent, never a second process. Deliberately not a heavyweight
scheduling library (APScheduler et al.): the whole requirement is "check
every N seconds whether either of two providers is due, and if so run the
existing sync once" — a single `asyncio.Task` with a sleep loop is simpler,
has zero new dependencies, and is trivially bounded/cancellable on
shutdown. See docs/DECISIONS.md for the fuller rationale.

Phase 10B's proactive routines (app/routine_service.py) reuse this exact
same loop/session/tick cycle rather than a second background task — each
tick and each startup catch-up checks both integration schedules and
routine schedules in the same pass.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Callable

import httpx
from sqlalchemy.orm import sessionmaker

from app import routine_service, scheduler_service
from app.credential_store import CredentialStore

logger = logging.getLogger("jarvis.scheduler")

DEFAULT_TICK_INTERVAL_SECONDS = 30.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchedulerRuntime:
    """One instance per running backend process, held on `app.state`. Its
    own `_task` field is the only thing that could ever create a second
    concurrent loop — `start()` refuses to run twice."""

    def __init__(
        self,
        session_factory: sessionmaker,
        credential_store: CredentialStore,
        http_client: httpx.Client,
        *,
        clock: Callable[[], datetime] = _utcnow,
        tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._credential_store = credential_store
        self._http_client = http_client
        self._clock = clock
        self._tick_interval_seconds = tick_interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return  # already running — never a second concurrent loop
        await asyncio.to_thread(self._run_startup_catchup)
        self._task = asyncio.create_task(self._loop(), name="jarvis-integration-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def _run_startup_catchup(self) -> None:
        session = self._session_factory()
        try:
            scheduler_service.startup_catchup(session, self._credential_store, self._http_client, self._clock)
        except Exception:
            logger.exception("Startup integration-sync catch-up failed; continuing without it.")
        try:
            routine_service.startup_catchup(session, self._clock)
        except Exception:
            logger.exception("Startup routine catch-up failed; continuing without it.")
        finally:
            session.close()

    def _run_tick(self) -> None:
        session = self._session_factory()
        try:
            scheduler_service.tick(session, self._credential_store, self._http_client, self._clock)
        except Exception:
            logger.exception("Scheduled integration-sync tick failed; will retry on the next tick.")
        try:
            routine_service.tick(session, self._clock)
        except Exception:
            logger.exception("Scheduled routine tick failed; will retry on the next tick.")
        finally:
            session.close()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._tick_interval_seconds)
            await asyncio.to_thread(self._run_tick)
