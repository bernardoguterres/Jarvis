"""Confirms migration 0017 -> 0018 (Phase 12F Decision Room) creates the
eight new tables with no data loss to existing tables, that the partial
unique index enforces evidence-add idempotency at the database level,
that the version-number unique constraints hold for both brief and final
versions, and that a fresh migration chain reaches the current real head
(never a hardcoded revision literal)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.config import Config

# Registers ResearchWorkspace's table into Base.metadata — Decision's own
# research_workspace_id FK target must be resolvable when the ORM
# configures mappers below, even in tests that never construct a
# ResearchWorkspace row directly (mirrors test_migration_0017.py's own
# need to import it for the identical reason).
import app.models_research  # noqa: F401
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


def test_migration_0018_preserves_data_created_before_it(data_dir: Path) -> None:
    import json
    from datetime import datetime, timezone

    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0017")
    assert read_db_revision(settings.database_path) == "0017"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        from app.models_memory import StructuredRecord

        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"title": "Pre-Phase-12F record"}),
        )
        session.add(record)
        session.commit()
        recorded_id = record.id
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")
    # Deliberately never a hardcoded "head is exactly 0018" literal — the
    # next phase's migration would immediately make that stale, exactly
    # the defect class D95/D96 already found and fixed once before.
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in (
            "decisions", "decision_options", "decision_criteria", "decision_assessments",
            "decision_evidence_links", "decision_factors", "decision_brief_versions",
            "decision_final_versions", "decision_outcome_reviews",
        ):
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
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    from app.migration_info import upgrade_database_to_head

    upgrade_database_to_head(settings.database_url)

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from app.models_decisions import Decision, DecisionEvidenceLink

        decision = Decision(title="x", included_domain_slugs_json="[]", status="draft")
        session.add(decision)
        session.flush()
        session.add(
            DecisionEvidenceLink(
                decision_id=decision.id, source_type="conversation", source_id="fixed-source-id",
                title_snapshot="t", snippet_snapshot="s", stance="supporting", status="active",
            )
        )
        session.commit()

        session.add(
            DecisionEvidenceLink(
                decision_id=decision.id, source_type="conversation", source_id="fixed-source-id",
                title_snapshot="t2", snippet_snapshot="s2", stance="contradicting", status="active",
            )
        )
        import pytest
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


def test_unique_constraints_on_brief_and_final_version_numbers(data_dir: Path) -> None:
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    from app.migration_info import upgrade_database_to_head

    upgrade_database_to_head(settings.database_url)

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        from datetime import datetime, timezone

        from app.models_decisions import (
            Decision,
            DecisionBriefVersion,
            DecisionFinalVersion,
            DecisionOption,
        )

        decision = Decision(title="x", included_domain_slugs_json="[]", status="draft")
        session.add(decision)
        session.flush()
        option = DecisionOption(decision_id=decision.id, name="opt", status="active", rank=1)
        session.add(option)
        session.flush()

        session.add(
            DecisionBriefVersion(
                decision_id=decision.id, version_number=1, source="deterministic", status="ok", title="t",
                sections_json="{}", citations_json="[]", evidence_ids_json="[]", validation_json="[]",
            )
        )
        session.commit()
        session.add(
            DecisionBriefVersion(
                decision_id=decision.id, version_number=1, source="deterministic", status="ok", title="t2",
                sections_json="{}", citations_json="[]", evidence_ids_json="[]", validation_json="[]",
            )
        )
        import pytest
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            DecisionFinalVersion(
                decision_id=decision.id, version_number=1, selected_option_id=option.id, rationale="r",
                decision_confidence=3, decided_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        session.add(
            DecisionFinalVersion(
                decision_id=decision.id, version_number=1, selected_option_id=option.id, rationale="r2",
                decision_confidence=4, decided_at=datetime.now(timezone.utc),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
