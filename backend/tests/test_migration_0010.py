"""Confirms migration 0009 -> 0010 (Phase 10B routines) seeds all three
fixed routine schedules disabled by default. Forward-only — 0001-0009
untouched."""

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


def test_migration_0010_seeds_disabled_routine_schedules(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0009")
    assert read_db_revision(settings.database_path) == "0009"

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        rows = conn.execute(
            "SELECT routine_type, enabled FROM routine_schedules ORDER BY routine_type"
        ).fetchall()
        assert rows == [("evening_checkin", 0), ("morning_briefing", 0), ("weekly_review", 0)]

        try:
            conn.execute(
                "INSERT INTO routine_schedules (routine_type, enabled, local_time, timezone, selected_domains_json, consecutive_failure_count, created_at, updated_at) "
                "VALUES ('bogus', 0, '08:00', 'UTC', '[]', 0, datetime('now'), datetime('now'))"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "routine_runs" in tables
    finally:
        conn.close()
