"""Confirms migration 0013 -> 0014 (Phase 12C Mission Focus) creates the
new table plus its real database-level enforcement (partial unique
indexes, max-5-active triggers), with no data loss to existing tables.
Forward-only — 0001-0013 untouched."""

from __future__ import annotations

import sqlite3
import uuid
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


def _insert_pin(conn: sqlite3.Connection, rank: int, status: str = "active", source_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO mission_focus_pins "
        "(id, source_type, source_id, domain_slug, source_title_snapshot, rank, next_action, status, pinned_at, created_at, updated_at) "
        "VALUES (?, 'life_task', ?, 'life', 't', ?, 'do it', ?, datetime('now'), datetime('now'), datetime('now'))",
        (uuid.uuid4().hex, source_id or uuid.uuid4().hex, rank, status),
    )
    conn.commit()


def test_migration_0014_creates_mission_focus_table_and_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0013")
    assert read_db_revision(settings.database_path) == "0013"

    # Seed a pre-existing briefing_settings row to prove untouched data survival.
    conn = sqlite3.connect(str(settings.database_path))
    conn.execute("UPDATE briefing_settings SET include_body = 1 WHERE id = 'singleton'")
    conn.commit()
    conn.close()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        row = conn.execute("SELECT include_body FROM briefing_settings WHERE id = 'singleton'").fetchone()
        assert row == (1,)

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "mission_focus_pins" in tables

        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert "uq_mission_focus_active_source" in indexes
        assert "uq_mission_focus_active_rank" in indexes

        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
        assert "trg_mission_focus_max_active_pins_insert" in triggers
        assert "trg_mission_focus_max_active_pins_update" in triggers

        # Real enforcement, not just presence of the objects.
        for rank in range(1, 6):
            _insert_pin(conn, rank)
        try:
            _insert_pin(conn, 6)
            raise AssertionError("6th active pin should have been rejected")
        except sqlite3.IntegrityError:
            pass

        dup_source = uuid.uuid4().hex
        conn.execute("UPDATE mission_focus_pins SET status='unpinned' WHERE rank IN (2,3,4,5)")
        conn.commit()
        _insert_pin(conn, 2, source_id=dup_source)
        try:
            _insert_pin(conn, 3, source_id=dup_source)
            raise AssertionError("duplicate active source should have been rejected")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_full_fresh_migration_chain_reaches_0014(data_dir: Path) -> None:
    """Named for the 0014 (Mission Focus) migration this file otherwise
    covers, but asserts against whatever the current head actually is
    (0015+, Mission Control, as of this writing) — never a hardcoded
    revision id, since forward-only migrations after 0014 are expected."""
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()
