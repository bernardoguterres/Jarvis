"""Confirms migration 0015 -> 0016 (Phase 12D Unified Recall) creates the
new `recall_fts` table with no data loss to existing tables, that
existing installations get backfilled automatically at startup, and that
a fresh migration chain reaches the current real head (never a hardcoded
revision literal — see D95/D96's own correction of that exact mistake)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.migration_info import get_head_revision, read_db_revision
from app.models import Domain
from app.models_memory import StructuredRecord
from app.seed import seed_domains

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_0016_preserves_data_created_before_it(data_dir: Path) -> None:
    import json
    from datetime import datetime, timezone

    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0015")
    assert read_db_revision(settings.database_path) == "0015"

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=datetime.now(timezone.utc),
            payload_json=json.dumps({"title": "Pre-Phase-12D record"}),
        )
        session.add(record)
        session.commit()
        recorded_id = record.id
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()

    import sqlite3

    conn = sqlite3.connect(str(settings.database_path))
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "recall_fts" in tables
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


def test_startup_backfills_recall_index_for_a_pre_0016_installation(data_dir: Path, monkeypatch) -> None:
    """A database migrated only to 0015 (recall_fts does not exist), then
    upgraded to head by the app's own startup path, must end up with its
    existing content backfilled into recall_fts — never left empty just
    because the installation predates Phase 12D."""
    import json as _json
    from datetime import datetime, timezone

    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0015")

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        session.add(
            StructuredRecord(
                domain_id=life.id, record_type="life_task", occurred_at=datetime.now(timezone.utc),
                payload_json=_json.dumps({"title": "Backfill target task"}),
            )
        )
        session.commit()
    engine.dispose()

    # Mirrors the real deployment order (scripts/jarvisctl.sh runs
    # `alembic upgrade head` as its own step before starting uvicorn) —
    # the FastAPI app's own lifespan never runs migrations itself, only
    # the one-time backfill-if-empty sweep against whatever schema is
    # already at head by the time it starts.
    command.upgrade(_alembic_config(settings.database_url), "head")

    monkeypatch.setenv("JARVIS_DATA_DIR", str(data_dir))
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        resp = test_client.get("/api/recall/search", params={"q": "Backfill"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1
