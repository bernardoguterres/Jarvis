"""The background scheduler: one asyncio task started and stopped by
FastAPI's lifespan (app/main.py), not a cron job or separate process.
Each tick checks whether an integration sync, a routine or a backup is
due and runs it once. A plain sleep loop is enough here and adds no
dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Callable

import httpx
from sqlalchemy.orm import sessionmaker

from app import routine_service, scheduler_service
from app.backup_service import run_due_backups
from app.config import Settings
from app.credential_store import CredentialStore

logger = logging.getLogger("jarvis.scheduler")

DEFAULT_TICK_INTERVAL_SECONDS = 30.0
DEFAULT_BACKUP_CHECK_INTERVAL_SECONDS = 300.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchedulerRuntime:
    """One instance per running backend process, held on `app.state`. Its
    own `_task` field is the only thing that could ever create a second
    concurrent loop, so `start()` refuses to run twice."""

    def __init__(
        self,
        session_factory: sessionmaker,
        credential_store: CredentialStore,
        http_client: httpx.Client,
        *,
        clock: Callable[[], datetime] = _utcnow,
        tick_interval_seconds: float = DEFAULT_TICK_INTERVAL_SECONDS,
        backup_settings: Settings | None = None,
        backup_check_interval_seconds: float = DEFAULT_BACKUP_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._credential_store = credential_store
        self._http_client = http_client
        self._clock = clock
        self._tick_interval_seconds = tick_interval_seconds
        self._backup_settings = backup_settings
        self._backup_check_interval_seconds = backup_check_interval_seconds
        # Startup already ran a backup due-check (app/main.py), so the first
        # scheduled check waits one full interval.
        self._last_backup_check = time.monotonic()
        self._task: asyncio.Task | None = None
        # Held for the whole of a tick's work, which runs in a worker
        # thread. Cancelling the asyncio task does not stop that thread, so
        # stop() waits on this lock: once stop() returns, no scheduled job
        # is touching the database (a restore relies on this).
        self._work_lock = threading.Lock()
        # Set by stop() before it waits on the lock. A tick whose thread had
        # already been scheduled but had not yet taken the lock sees it and
        # does nothing, so no job can start after stop() returns.
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None:
            return  # already running; never a second concurrent loop
        self._stopping = False
        await asyncio.to_thread(self._run_startup_catchup)
        self._task = asyncio.create_task(self._loop(), name="jarvis-integration-scheduler")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stopping = True
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        await asyncio.to_thread(self._wait_for_running_work)

    def _wait_for_running_work(self) -> None:
        with self._work_lock:
            pass

    def _run_startup_catchup(self) -> None:
        with self._work_lock:
            self._run_startup_catchup_locked()

    def _run_startup_catchup_locked(self) -> None:
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
        with self._work_lock:
            if self._stopping:
                return
            self._run_tick_locked()
            self._maybe_run_backups()

    def _maybe_run_backups(self) -> None:
        if self._backup_settings is None:
            return
        now = time.monotonic()
        if now - self._last_backup_check < self._backup_check_interval_seconds:
            return
        self._last_backup_check = now
        try:
            created = run_due_backups(self._backup_settings)
            for result in created:
                logger.info("Scheduled %s backup created: %s", result.category, result.filename)
        except Exception:
            logger.exception("Scheduled backup due-check failed; will retry on the next check.")

    def _run_tick_locked(self) -> None:
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
