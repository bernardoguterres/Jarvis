"""Confirms migration 0018 -> 0019 (hardening pass: needs_review action
status) preserves existing action_proposals rows, allows needs_review to
be stored and read back, still rejects an invalid status, and that a
fresh migration chain reaches the current real head (never a hardcoded
revision literal). Uses only temporary databases (pytest's `data_dir`
fixture) — never ~/JarvisData or any real database."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
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


def test_migration_0019_preserves_existing_action_rows(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0018")
    assert read_db_revision(settings.database_path) == "0018"

    # Insert a row directly at the pre-migration schema, the way a real
    # existing action_proposals row would look before this hardening pass.
    conn = sqlite3.connect(str(settings.database_path))
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO action_proposals
            (id, capability_id, domain_id, permission_level, arguments_json, reason, expected_effect,
             payload_digest, status, source, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "legacy-row-1", "google_calendar.event.create", None, "confirm", "{}", "legacy reason",
                "legacy effect", "x" * 64, "succeeded", "test", now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(_alembic_config(settings.database_url), "head")
    # Deliberately never a hardcoded "head is exactly 0019" literal — the
    # next phase's migration would immediately make that stale.
    assert read_db_revision(settings.database_path) == get_head_revision()

    conn = sqlite3.connect(str(settings.database_path))
    try:
        row = conn.execute("SELECT status FROM action_proposals WHERE id = ?", ("legacy-row-1",)).fetchone()
        assert row is not None
        assert row[0] == "succeeded"
    finally:
        conn.close()


def test_needs_review_status_can_be_stored_and_read_after_migration(data_dir: Path) -> None:
    from app.migration_info import upgrade_database_to_head

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        from app.models_actions import ActionProposal

        proposal = ActionProposal(
            capability_id="google_calendar.event.create",
            domain_id=life.id,
            permission_level="confirm",
            arguments_json=json.dumps({}),
            reason="test",
            expected_effect="test",
            payload_digest="y" * 64,
            status="needs_review",
            source="test",
            error_summary="Verify the calendar directly before retrying.",
        )
        session.add(proposal)
        session.commit()
        proposal_id = proposal.id
    engine.dispose()

    # Re-open a fresh session/engine to prove this was actually persisted,
    # not merely held in the ORM identity map.
    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        from app.models_actions import ActionProposal

        reread = session.get(ActionProposal, proposal_id)
        assert reread is not None
        assert reread.status == "needs_review"
    engine.dispose()


def test_invalid_action_status_still_rejected_after_migration(data_dir: Path) -> None:
    from app.migration_info import upgrade_database_to_head

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)

    conn = sqlite3.connect(str(settings.database_path))
    try:
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                """INSERT INTO action_proposals
                (id, capability_id, domain_id, permission_level, arguments_json, reason, expected_effect,
                 payload_digest, status, source, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "bad-status-row", "google_calendar.event.create", None, "confirm", "{}", "r", "e",
                    "z" * 64, "not_a_real_status", "test", now, now,
                ),
            )
            conn.commit()
            raise AssertionError("expected the status CHECK constraint to reject this row")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_application_starts_against_an_upgraded_database(data_dir: Path) -> None:
    """Migrating an existing (pre-0019) database to head must leave the
    app able to start normally — not just the schema, the full FastAPI
    app construction (route registration, etc.). The `data_dir` fixture
    already points JARVIS_DATA_DIR at this exact isolated path."""
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0018")
    command.upgrade(_alembic_config(settings.database_url), "head")

    from app.main import create_app

    app = create_app()
    assert len(app.routes) > 0


def test_application_starts_against_a_fresh_head_database(data_dir: Path) -> None:
    """A brand-new install (never at 0018) must also reach head and start
    cleanly — not only the upgrade path from an existing database."""
    from app.migration_info import upgrade_database_to_head

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    assert read_db_revision(settings.database_path) == get_head_revision()

    from app.main import create_app

    app = create_app()
    assert len(app.routes) > 0


def test_full_fresh_migration_chain_reaches_head(data_dir: Path) -> None:
    from alembic import command

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "head")
    assert read_db_revision(settings.database_path) == get_head_revision()
