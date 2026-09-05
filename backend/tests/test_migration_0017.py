"""Confirms migration 0016 -> 0017 (Phase 12E Research Workspace) creates
the four new tables with no data loss to existing tables, that the
partial unique index enforces evidence idempotency at the database level,
and that a fresh migration chain reaches the current real head (never a
hardcoded revision literal)."""

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


def test_migration_0017_preserves_data_created_before_it(data_dir: Path) -> None:
    import json
    from datetime import datetime, timezone

    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0016")
    assert read_db_revision(settings.database_path) == "0016"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        from app.models_memory import StructuredRecord

        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"title": "Pre-Phase-12E record"}),
        )
        session.add(record)
        session.commit()
        recorded_id = record.id
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in ("research_workspaces", "research_evidence", "research_notes", "research_brief_versions"):
            assert table in tables
        row = conn.execute("SELECT id FROM structured_records WHERE id = ?", (recorded_id,)).fetchone()
        assert row is not None
    finally:
        conn.close()


def test_full_fresh_migration_chain_reaches_head(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()


def test_database_level_partial_unique_index_blocks_duplicate_active_evidence(data_dir: Path) -> None:
    """The service layer's own check-then-insert is only the first line
    of defense — this proves the database itself refuses a second
    simultaneously-active (workspace_id, source_type, source_id) row."""
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    from app.migration_info import upgrade_database_to_head

    upgrade_database_to_head(settings.database_url)

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from app.models_research import ResearchEvidence, ResearchWorkspace

        ws = ResearchWorkspace(title="x", included_domain_slugs_json="[]", status="active")
        session.add(ws)
        session.flush()
        session.add(
            ResearchEvidence(
                workspace_id=ws.id, source_type="conversation", source_id="fixed-source-id",
                title_snapshot="t", snippet_snapshot="s", classification="unresolved", status="active",
            )
        )
        session.commit()

        session.add(
            ResearchEvidence(
                workspace_id=ws.id, source_type="conversation", source_id="fixed-source-id",
                title_snapshot="t2", snippet_snapshot="s2", classification="supporting", status="active",
            )
        )
        import pytest
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_unique_constraint_on_workspace_and_version_number(data_dir: Path) -> None:
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    from app.migration_info import upgrade_database_to_head

    upgrade_database_to_head(settings.database_url)

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from app.models_research import ResearchBriefVersion, ResearchWorkspace

        ws = ResearchWorkspace(title="x", included_domain_slugs_json="[]", status="active")
        session.add(ws)
        session.flush()
        session.add(
            ResearchBriefVersion(
                workspace_id=ws.id, version_number=1, source="deterministic", status="ok", title="t",
                sections_json="[]", citations_json="[]", evidence_ids_json="[]", validation_json="[]",
            )
        )
        session.commit()
        session.add(
            ResearchBriefVersion(
                workspace_id=ws.id, version_number=1, source="deterministic", status="ok", title="t2",
                sections_json="[]", citations_json="[]", evidence_ids_json="[]", validation_json="[]",
            )
        )
        import pytest
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
