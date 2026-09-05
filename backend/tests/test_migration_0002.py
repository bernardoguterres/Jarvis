"""Confirms migrating an existing Phase 2 (revision 0001) database forward to
0002 preserves all existing data and adds the new agent_runs table cleanly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.migration_info import get_head_revision, read_db_revision
from app.models import Conversation, Domain, Message
from app.seed import seed_domains

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_from_phase2_schema_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    # Start on the Phase 2 schema only (revision 0001), matching what an
    # existing Phase 2 installation would actually have on disk.
    command.upgrade(_alembic_config(settings.database_url), "0001")
    assert read_db_revision(settings.database_path) == "0001"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        body = session.query(Domain).filter_by(slug="body").one()
        conv = Conversation(domain_id=body.id, title="Pre-migration conversation")
        session.add(conv)
        session.flush()
        session.add(Message(conversation_id=conv.id, role="user", content="Pre-migration message"))
        session.commit()
        recorded_conv_id = conv.id
        recorded_domain_ids = {d.slug: d.id for d in session.query(Domain).all()}
    engine.dispose()

    # Now migrate forward to head (0002).
    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        # agent_runs table now exists.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "agent_runs" in tables

        # All prior data is untouched.
        domain_ids = {
            row[0]: row[1] for row in conn.execute("SELECT slug, id FROM domains").fetchall()
        }
        assert domain_ids == recorded_domain_ids

        conv_row = conn.execute(
            "SELECT title FROM conversations WHERE id=?", (recorded_conv_id,)
        ).fetchone()
        assert conv_row == ("Pre-migration conversation",)

        message_row = conn.execute(
            "SELECT content FROM messages WHERE conversation_id=?", (recorded_conv_id,)
        ).fetchone()
        assert message_row == ("Pre-migration message",)

        agent_runs_count = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
        assert agent_runs_count == 0
    finally:
        conn.close()
