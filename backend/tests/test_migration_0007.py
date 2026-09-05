"""Confirms the forward-only migration 0006 -> 0007 (Google Health breadth
correction) adds the new daily-summary columns and the sessions table
without disturbing existing data."""

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


def test_migration_0007_adds_columns_and_sessions_table_preserving_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0006")
    assert read_db_revision(settings.database_path) == "0006"

    conn = sqlite3.connect(str(settings.database_path))
    try:
        conn.execute(
            "INSERT INTO google_health_daily_summaries (id, date, steps, fetched_at) VALUES "
            "('row-1', '2026-08-01', 8000, datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        # Pre-existing data survives the column additions untouched.
        row = conn.execute("SELECT steps FROM google_health_daily_summaries WHERE id='row-1'").fetchone()
        assert row == (8000,)

        columns = {r[1] for r in conn.execute("PRAGMA table_info(google_health_daily_summaries)").fetchall()}
        for expected in (
            "floors",
            "active_zone_minutes",
            "active_calories_kcal",
            "heart_rate_avg_bpm",
            "oxygen_saturation_avg_percent",
            "respiratory_rate_breaths_per_min",
            "vo2_max",
            "body_fat_percent",
            "blood_glucose_mg_dl",
            "source_platforms_json",
        ):
            assert expected in columns, f"missing column: {expected}"

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "google_health_sessions" in tables

        conn.execute(
            "INSERT INTO google_health_sessions (id, session_type, external_id, start_time, end_time, fetched_at) "
            "VALUES ('sess-1', 'sleep', 'ext-1', datetime('now'), datetime('now'), datetime('now'))"
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM google_health_sessions").fetchone()[0] == 1

        # The tightened session_type CHECK constraint rejects an invalid value.
        try:
            conn.execute(
                "INSERT INTO google_health_sessions (id, session_type, external_id, start_time, end_time, fetched_at) "
                "VALUES ('sess-2', 'bogus', 'ext-2', datetime('now'), datetime('now'), datetime('now'))"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised
    finally:
        conn.close()
