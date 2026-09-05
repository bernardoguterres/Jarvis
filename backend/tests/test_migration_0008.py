"""Confirms the forward-only migration 0007 -> 0008 widens
heart_rate_avg_bpm/min/max from Integer to Float without disturbing
existing data — the real bug this fixes (D66): a stored fractional value
under the old Integer declaration caused a genuine unhandled 500 when read
back through the (also Integer-typed) Pydantic schema."""

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


def test_migration_0008_widens_heart_rate_columns_to_float(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0007")
    assert read_db_revision(settings.database_path) == "0007"

    conn = sqlite3.connect(str(settings.database_path))
    try:
        conn.execute(
            "INSERT INTO google_health_daily_summaries (id, date, heart_rate_avg_bpm, fetched_at) VALUES "
            "('row-1', '2026-08-01', 64, datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        # Pre-existing data survives the type widening.
        row = conn.execute("SELECT heart_rate_avg_bpm FROM google_health_daily_summaries WHERE id='row-1'").fetchone()
        assert row == (64,)

        # A fractional value can now be stored and read back — the actual bug.
        conn.execute(
            "INSERT INTO google_health_daily_summaries (id, date, heart_rate_avg_bpm, fetched_at) VALUES "
            "('row-2', '2026-08-02', 64.51058794220229, datetime('now'))"
        )
        conn.commit()
        row2 = conn.execute("SELECT heart_rate_avg_bpm FROM google_health_daily_summaries WHERE id='row-2'").fetchone()
        assert abs(row2[0] - 64.51058794220229) < 1e-9
    finally:
        conn.close()
