"""Confirms migrating an existing Phase 8 (revision 0004) database forward
to 0005 preserves all existing data and adds the new integration/document
tables cleanly."""

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


def test_migration_from_phase8_schema_preserves_data(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    command.upgrade(_alembic_config(settings.database_url), "0004")
    assert read_db_revision(settings.database_path) == "0004"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from app import action_service

        proposal = action_service.propose_action(
            session,
            capability_id="memory.create",
            domain_id=None,
            arguments={"scope": "global", "kind": "fact", "title": "Pre-Phase-9", "content": "c"},
            reason="test",
        )
        recorded_proposal_id = proposal.id
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()}
        for expected in (
            "integration_connections",
            "calendar_calendars",
            "calendar_event_cache",
            "google_health_daily_summaries",
            "documents",
            "document_chunks",
            "document_fts",
        ):
            assert expected in tables, f"missing table: {expected}"

        proposal_row = conn.execute("SELECT reason FROM action_proposals WHERE id=?", (recorded_proposal_id,)).fetchone()
        assert proposal_row == ("test",)

        assert conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0] == 6
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM integration_connections").fetchone()[0] == 0

        # A pre-existing action_proposal row must still satisfy the widened
        # capability CHECK constraint after the ALTER.
        conn.execute(
            "INSERT INTO action_proposals (id, capability_id, domain_id, permission_level, arguments_json, "
            "reason, expected_effect, payload_digest, status, source, created_at, updated_at) VALUES "
            "('test-cal-id', 'google_calendar.event.create', NULL, 'confirm', '{}', 'r', 'e', 'd', 'proposed', "
            "'manual_proposal', datetime('now'), datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    engine2 = build_engine(settings.database_url)
    with build_sessionmaker(engine2)() as session:
        from app import document_service

        body = session.query(Domain).filter_by(slug="body").one()
        doc = document_service.import_document(
            session, settings, domain_id=body.id, original_filename="post-migration.txt", data=b"writability check"
        )
        assert doc.id
    engine2.dispose()
