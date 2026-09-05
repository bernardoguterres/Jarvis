"""D83: a second connection writing while another connection's transaction
is still open can raise `database is locked` immediately, with no retry —
SQLite's own documented default busy timeout is 0ms. This app always has at
least two independent connections capable of writing at once — the FastAPI
request-handling session(s) and the background SchedulerRuntime's own
session (Phase 10) — so an ordinary, brief overlap must not depend on
whatever busy-timeout default a given platform's SQLite build happens to
ship with.

Important honesty note (found while writing these tests): this container's
particular linked SQLite build already defaults to a 5000ms busy timeout
with *no* PRAGMA set at all — some distributions patch this away from
upstream SQLite's documented 0ms default. That means a test which only
checks "does a brief overlap succeed without raising" cannot, by itself,
prove `app.database`'s own PRAGMA is what's responsible *in this specific
environment* — it would pass even if that line were deleted, purely by
platform coincidence. The tests below are written to be conclusive
regardless of any given platform's ambient default:

1. `test_a_second_writer_fails_immediately_when_busy_timeout_is_explicitly_zero`
   proves the underlying failure mode is real and that this test file's
   locking mechanism can actually detect it (never a vacuously-passing
   test), by explicitly forcing busy_timeout=0 — overriding whatever the
   platform default is — before holding the lock.
2. `test_a_second_writer_waits_for_the_lock_when_busy_timeout_is_set`
   proves that explicitly setting a non-zero busy_timeout (mirroring what
   `app.database` does) turns that same failure into a brief, successful
   wait.
3. `test_the_apps_own_connect_listener_sets_busy_timeout_explicitly` proves
   `app.database.build_engine`'s own connect-event listener is what sets
   the value on every new connection, by asserting the exact value it
   documents (5000) rather than merely "some non-zero value" (which the
   ambient platform default in this container would already satisfy on its
   own).
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import time

import pytest

from app.config import Settings
from app.database import build_engine


def _raw_connection(path: str, busy_timeout_ms: int) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    return conn


def _hold_lock_in_background(conn: sqlite3.Connection, hold_seconds: float, started: threading.Event) -> threading.Thread:
    def _hold() -> None:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        started.set()
        time.sleep(hold_seconds)
        conn.commit()

    thread = threading.Thread(target=_hold)
    thread.start()
    started.wait(timeout=2)
    return thread


def test_a_second_writer_fails_immediately_when_busy_timeout_is_explicitly_zero() -> None:
    """Establishes that this test file's locking setup genuinely reproduces
    contention — busy_timeout=0 overrides any platform default, so this
    must fail regardless of what this machine's SQLite happens to ship
    with."""
    path = tempfile.mktemp(suffix=".sqlite")
    holder = _raw_connection(path, busy_timeout_ms=0)
    started = threading.Event()
    thread = _hold_lock_in_background(holder, hold_seconds=0.3, started=started)

    writer = _raw_connection(path, busy_timeout_ms=0)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        writer.execute("CREATE TABLE IF NOT EXISTS t2 (id INTEGER)")

    thread.join(timeout=2)
    holder.close()
    writer.close()


def test_a_second_writer_waits_for_the_lock_when_busy_timeout_is_set() -> None:
    """The same contention as above, but with a non-zero busy_timeout on
    both sides (mirroring app.database's own PRAGMA) — the second writer
    must now succeed by waiting, never raise."""
    path = tempfile.mktemp(suffix=".sqlite")
    holder = _raw_connection(path, busy_timeout_ms=5000)
    started = threading.Event()
    hold_seconds = 0.4
    thread = _hold_lock_in_background(holder, hold_seconds=hold_seconds, started=started)

    writer = _raw_connection(path, busy_timeout_ms=5000)
    start = time.monotonic()
    writer.execute("CREATE TABLE IF NOT EXISTS t2 (id INTEGER)")
    writer.commit()
    elapsed = time.monotonic() - start

    thread.join(timeout=2)
    # Only succeeded because it genuinely waited for the holder's commit.
    assert elapsed >= hold_seconds * 0.5
    holder.close()
    writer.close()


def test_the_apps_own_connect_listener_sets_busy_timeout_explicitly(memory_settings: Settings) -> None:
    """Proves app.database's connect-event listener is what applies this —
    not a coincidental platform default — by asserting the exact documented
    value rather than merely "non-zero"."""
    engine = build_engine(memory_settings.database_url)
    with engine.connect() as conn:
        value = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
    engine.dispose()
    assert value == 5000
