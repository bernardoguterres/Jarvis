"""Confirms migrating an existing Phase 4 (revision 0003) database forward to
0004 preserves all existing data and adds the new action/hook/skill tables
cleanly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.migration_info import get_head_revision, read_db_revision
from app.models import Domain
from app.seed import seed_domains

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_from_phase4_schema_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0003")
    assert read_db_revision(settings.database_path) == "0003"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from app import memory_service

        item = memory_service.create_memory(
            session, scope="global", domain_id=None, kind="fact", title="Pre-Phase-8", content="c"
        )
        recorded_memory_id = item.id
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        for expected in (
            "action_proposals",
            "action_audit_events",
            "hook_events",
            "skills",
            "skill_versions",
        ):
            assert expected in tables, f"missing table: {expected}"

        memory_row = conn.execute(
            "SELECT title FROM memory_items WHERE id=?", (recorded_memory_id,)
        ).fetchone()
        assert memory_row == ("Pre-Phase-8",)

        domains_count = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
        assert domains_count == 6

        assert conn.execute("SELECT COUNT(*) FROM action_proposals").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 0
    finally:
        conn.close()

    # The database remains fully usable after migration: can propose an action.
    engine2 = build_engine(settings.database_url)
    with build_sessionmaker(engine2)() as session:
        from app import action_service

        proposal = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "Post-migration", "content": "c"},
            reason="test",
        )
        assert proposal.id
        assert proposal.status == "proposed"
    engine2.dispose()
