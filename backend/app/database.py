"""SQLAlchemy engine/session setup, with SQLite foreign-key enforcement."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # SQLite's own documented default busy timeout is 0ms: a second
    # connection attempting to write while another connection's transaction
    # is still open raises "database is locked" immediately, with no retry
    # at all, unless the *linked* SQLite library's own compile-time default
    # happens to differ (some distributions patch this; relying on that is
    # exactly the fragility being avoided here). This app always has at
    # least two independent connections capable of writing at once — the
    # FastAPI request-handling session(s) and the background
    # SchedulerRuntime's own session (Phase 10) — so an ordinary, brief
    # overlap (a scheduled sync's commit landing at the same moment as a
    # user saving a note) must not depend on whatever a given platform's
    # SQLite build happens to default to. Setting this explicitly makes the
    # behavior deterministic everywhere: the caller waits up to 5s for the
    # lock to clear — comfortably more than this app's uniformly small, fast
    # transactions ever need — rather than failing immediately on any
    # platform where the compiled default is 0. See docs/DECISIONS.md D83.
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, connect_args={"check_same_thread": False})


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
