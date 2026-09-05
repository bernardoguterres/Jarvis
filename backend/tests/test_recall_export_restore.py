"""Phase 12D: Recall survives export/restore. `recall_fts` is a derived,
rebuildable index — never authoritative — so it travels with the raw
SQLite file copy exactly like `memory_fts`/`document_fts` already do; no
special restore-time handling is required, but this proves it actually
works end-to-end rather than merely asserting the design intent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Domain
from app.models_memory import StructuredRecord
from app.recall_index_service import sync_recall
from app.recall_service import search
from app.seed import seed_domains

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_recall_search_works_after_export_and_restore(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=NOW,
            payload_json=json.dumps({"title": "Renew passport before travel"}),
        )
        session.add(record)
        session.commit()
        sync_recall(session, "structured_record", record.id)
        session.commit()
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        result = search(session, "passport")
        assert len(result.results) == 1
        assert result.results[0].title == "Renew passport before travel"
    engine_b.dispose()


def test_recall_index_is_not_included_as_a_separate_export_component(tmp_path: Path) -> None:
    """The exported manifest's `included_components` names only real
    ground-truth data ("database") — recall_fts is a derived index
    living inside that same database file, never its own tracked
    component, exactly like memory_fts/document_fts."""
    install_a = _make_installation(tmp_path / "installation-a")
    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.manifest["included_components"] == ["database"]
