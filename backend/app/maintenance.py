"""Quiesces the API while the database file is being replaced.

A restore swaps the SQLite file underneath the running process. Before it
does, the restore route closes this gate: new /api requests get a 503,
and the restore waits until every request already in flight has
finished. Only then are pooled connections disposed and the file
replaced, so no handler can be holding a connection to the old file or
writing into the new one halfway through.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

_ALWAYS_OPEN = {"/api/health", "/api/session"}


class MaintenanceBusyError(Exception):
    pass


class MaintenanceGate:
    def __init__(self) -> None:
        self._in_flight = 0
        self._closed = False
        self._changed = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed

    @asynccontextmanager
    async def exclusive(self, *, timeout: float = 30.0):
        """Held by the request doing the maintenance. That request is
        itself counted as in flight, so this waits for the count to
        reach one."""
        if self._closed:
            raise MaintenanceBusyError("Another restore is already in progress.")
        self._closed = True
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while self._in_flight > 1:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise MaintenanceBusyError(
                        "Jarvis is still finishing other requests; try the restore again in a moment."
                    )
                self._changed.clear()
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout=min(remaining, 0.5))
                except asyncio.TimeoutError:
                    pass
            yield
        finally:
            self._closed = False

    class Middleware:
        def __init__(self, app, *, gate: "MaintenanceGate") -> None:
            self.app = app
            self.gate = gate

        async def __call__(self, scope, receive, send) -> None:
            path = scope.get("path", "") if scope["type"] == "http" else ""
            if not path.startswith("/api/") or path in _ALWAYS_OPEN:
                await self.app(scope, receive, send)
                return
            gate = self.gate
            if gate._closed:
                body = json.dumps({"detail": "Jarvis is restoring data. Try again in a moment."}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"application/json"), (b"retry-after", b"5")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            gate._in_flight += 1
            try:
                await self.app(scope, receive, send)
            finally:
                gate._in_flight -= 1
                gate._changed.set()
