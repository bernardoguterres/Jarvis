"""Confirms migration 0012 -> 0013 (Phase 12B briefing continuity) creates
the four new tables with no data loss to existing tables. Forward-only —
0001-0012 untouched."""

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


def test_migration_0013_creates_continuity_tables(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0012")
    assert read_db_revision(settings.database_path) == "0012"

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        # Pre-existing data untouched.
        row = conn.execute("SELECT include_body FROM briefing_settings WHERE id = 'singleton'").fetchone()
        assert row == (1,)

        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'briefing_%'"
            ).fetchall()
        }
        assert tables == {
            "briefing_settings",
            "briefing_snapshots",
            "briefing_item_states",
            "briefing_acknowledgements",
            "briefing_snoozes",
        }

        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_briefing_%'"
            ).fetchall()
        }
        for expected in (
            "ix_briefing_snapshots_consumer",
            "ix_briefing_item_states_stable_key",
            "ix_briefing_item_states_source_type",
            "ix_briefing_item_states_status",
            "ix_briefing_acknowledgements_lookup",
            "ix_briefing_snoozes_lookup",
            "ix_briefing_snoozes_snooze_until",
        ):
            assert expected in indexes
    finally:
        conn.close()
