"""Confirms the forward-only migration 0005 -> 0006 (Fitbit -> Google
Health provider replacement) renames the daily-summary table and the
context_snapshots column, tightens the integration_connections provider
CHECK constraint, and safely removes any pre-existing legacy 'fitbit'
connection row (never reinterpreting its credentials, never reusing its
tokens — none of which ever lived in this table anyway)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.migration_info import get_head_revision, read_db_revision

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_0006_renames_table_and_column_and_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0005")
    assert read_db_revision(settings.database_path) == "0005"

    conn = sqlite3.connect(str(settings.database_path))
    try:
        conn.execute(
            "INSERT INTO fitbit_daily_summaries (id, date, steps, fetched_at) VALUES "
            "('row-1', '2026-08-01', 9999, datetime('now'))"
        )
        conn.execute(
            "INSERT INTO integration_connections (provider, status, scopes_json, created_at, updated_at) VALUES "
            "('fitbit', 'connected', '[]', datetime('now'), datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "google_health_daily_summaries" in tables
        assert "fitbit_daily_summaries" not in tables

        # Cached daily-summary data is preserved across the rename.
        row = conn.execute("SELECT steps FROM google_health_daily_summaries WHERE id='row-1'").fetchone()
        assert row == (9999,)

        # The legacy fitbit connection row was removed — not selectable,
        # never reinterpreted as a Google credential (no tokens ever lived
        # in this table, so nothing to migrate there).
        remaining = conn.execute("SELECT provider FROM integration_connections").fetchall()
        assert ("fitbit",) not in remaining

        # The provider CHECK constraint now only allows the two current providers.
        try:
            conn.execute(
                "INSERT INTO integration_connections (provider, status, scopes_json, created_at, updated_at) VALUES "
                "('fitbit', 'connected', '[]', datetime('now'), datetime('now'))"
            )
            conn.commit()
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised, "provider CHECK constraint should reject 'fitbit' after migration 0006"

        conn.execute(
            "INSERT INTO integration_connections (provider, status, scopes_json, created_at, updated_at) VALUES "
            "('google_health', 'disconnected', '[]', datetime('now'), datetime('now'))"
        )
        conn.commit()

        columns = {row[1] for row in conn.execute("PRAGMA table_info(context_snapshots)").fetchall()}
        assert "google_health_summary_ids_json" in columns
        assert "fitbit_summary_ids_json" not in columns
    finally:
        conn.close()

    # The restored/migrated installation remains fully writable afterward.
    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        from app.models_integrations import GoogleHealthDailySummary

        assert session.query(GoogleHealthDailySummary).count() == 1
    engine.dispose()
