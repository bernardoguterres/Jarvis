"""Helpers for reading and validating Alembic migration revisions.

Used by the export service (to record the current schema revision) and the
import/restore service (to decide whether an archived database's schema is a
supported older revision, the current head, or an unsupported/future one).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _script_directory() -> ScriptDirectory:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def get_head_revision() -> str:
    """The most recent schema revision this codebase knows how to run."""
    return _script_directory().get_current_head()


def get_known_revisions() -> set[str]:
    """All revisions that exist anywhere in this codebase's migration history."""
    script_dir = _script_directory()
    return {revision.revision for revision in script_dir.walk_revisions()}


def read_db_revision(sqlite_path: Path) -> str | None:
    """Reads the alembic_version row directly from a SQLite file.

    Returns None if the database has no alembic_version table (unmigrated).
    """
    if not sqlite_path.exists():
        return None

    conn = sqlite3.connect(str(sqlite_path))
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        if cursor.fetchone() is None:
            return None
        cursor = conn.execute("SELECT version_num FROM alembic_version LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def is_known_revision(revision: str) -> bool:
    return revision in get_known_revisions()


def upgrade_database_to_head(database_url: str) -> None:
    """Runs `alembic upgrade head` programmatically against the given database URL."""
    from alembic import command

    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
