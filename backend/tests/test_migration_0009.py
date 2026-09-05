"""Confirms migration 0008 -> 0009 (Phase 10 automatic-resync schedules)
seeds both schedule rows disabled by default, without touching prior data.
Forward-only — 0001-0008 are untouched."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from app.config import Settings
from app.migration_info import get_head_revision, read_db_revision

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_0009_seeds_disabled_schedules(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0008")
    assert read_db_revision(settings.database_path) == "0008"

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        rows = conn.execute(
            "SELECT provider, enabled, interval_minutes FROM integration_sync_schedules ORDER BY provider"
        ).fetchall()
        assert rows == [("google_calendar", 0, 30), ("google_health", 0, 360)]

        # Provider CHECK constraint rejects an invalid provider.
        try:
            conn.execute(
                "INSERT INTO integration_sync_schedules (provider, enabled, interval_minutes, consecutive_failure_count, created_at, updated_at) "
                "VALUES ('bogus', 0, 30, 0, datetime('now'), datetime('now'))"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "integration_sync_runs" in tables
    finally:
        conn.close()
