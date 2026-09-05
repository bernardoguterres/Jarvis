"""Confirms migrating an existing Phase 3 (revision 0002) database forward to
0003 preserves all existing data and adds the new memory/record/context
tables (plus the FTS5 index) cleanly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.migration_info import get_head_revision, read_db_revision
from app.models import AgentRun, Conversation, Domain, Message
from app.seed import seed_domains

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_from_phase3_schema_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0002")
    assert read_db_revision(settings.database_path) == "0002"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        body = session.query(Domain).filter_by(slug="body").one()
        conv = Conversation(domain_id=body.id, title="Pre-Phase-4 conversation")
        session.add(conv)
        session.flush()
        msg = Message(conversation_id=conv.id, role="user", content="Pre-Phase-4 message")
        session.add(msg)
        session.flush()
        run = AgentRun(
            conversation_id=conv.id,
            user_message_id=msg.id,
            provider="fake",
            model="fake-model",
            status="succeeded",
            idempotency_key="pre-phase-4-key",
        )
        session.add(run)
        session.commit()
        recorded_conv_id = conv.id
        recorded_run_id = run.id
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
            "memory_items",
            "memory_versions",
            "domain_summaries",
            "domain_summary_versions",
            "structured_records",
            "context_snapshots",
            "memory_fts",
        ):
            assert expected in tables, f"missing table: {expected}"

        conv_row = conn.execute(
            "SELECT title FROM conversations WHERE id=?", (recorded_conv_id,)
        ).fetchone()
        assert conv_row == ("Pre-Phase-4 conversation",)

        run_row = conn.execute(
            "SELECT status FROM agent_runs WHERE id=?", (recorded_run_id,)
        ).fetchone()
        assert run_row == ("succeeded",)

        domains_count = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
        assert domains_count == 6

        # New tables start empty, not pre-populated with anything unexpected.
        assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM context_snapshots").fetchone()[0] == 0
    finally:
        conn.close()

    # The database remains fully usable after migration: can create a memory.
    engine2 = build_engine(settings.database_url)
    with build_sessionmaker(engine2)() as session:
        from app import memory_service

        item = memory_service.create_memory(
            session, scope="global", domain_id=None, kind="fact", title="Post-migration", content="c"
        )
        assert item.id
    engine2.dispose()
