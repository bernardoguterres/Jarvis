"""Confirms migration 0011 -> 0012 (Phase 12A briefing settings) seeds a
single settings row matching Bernardo's already-recorded privacy
selection: BODY included, MIND and PEOPLE excluded. Forward-only —
0001-0011 untouched."""

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


def test_migration_0012_seeds_default_privacy_selection(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0011")
    assert read_db_revision(settings.database_path) == "0011"

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        row = conn.execute(
            "SELECT include_body, include_mind, include_people FROM briefing_settings WHERE id = 'singleton'"
        ).fetchone()
    finally:
        conn.close()
    assert row == (1, 0, 0)
