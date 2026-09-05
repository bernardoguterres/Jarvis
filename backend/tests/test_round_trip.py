"""The Phase 2 required round-trip acceptance test.

Installation A creates data across both domains plus documents, summaries,
and skills; installation B imports the export and must recover everything,
remain writable, and produce its own verifiable export. A simulated failed
restore must leave the existing target installation intact.

Uses two isolated temporary directories only — never ~/JarvisData.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.backup_service import create_backup
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import RestoreError, restore_archive, validate_archive
from app.migration_info import get_head_revision, upgrade_database_to_head
from app.models import Conversation, Domain, Message
from app.seed import seed_domains

EXPECTED_SLUGS = {"body", "mind", "people", "path", "build", "life"}


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_full_export_import_round_trip(tmp_path: Path) -> None:
    # ------------------------------------------------------------------
    # Installation A: apply migrations, confirm six domains, create data.
    # ------------------------------------------------------------------
    install_a = _make_installation(tmp_path / "installation-a")

    engine_a = build_engine(install_a.database_url)
    session_factory_a = build_sessionmaker(engine_a)
    with session_factory_a() as session:
        seed_domains(session)
        domains = {d.slug: d for d in session.query(Domain).all()}
        assert set(domains.keys()) == EXPECTED_SLUGS

        body_conv = Conversation(domain_id=domains["body"].id, title="Knee check-in")
        build_conv = Conversation(domain_id=domains["build"].id, title="Alpha checkpoint")
        session.add_all([body_conv, build_conv])
        session.flush()

        body_message = Message(
            conversation_id=body_conv.id, role="user", content="Knee felt fine on today's run."
        )
        build_message = Message(
            conversation_id=build_conv.id, role="user", content="Shipped the tokenizer fix."
        )
        session.add_all([body_message, build_message])
        session.commit()

        recorded_body_conv_id = body_conv.id
        recorded_build_conv_id = build_conv.id
        recorded_domain_ids = {slug: d.id for slug, d in domains.items()}
    engine_a.dispose()

    # Read back via raw sqlite3 (not the ORM) so the later comparison against
    # installation B's raw sqlite3 reads is a true byte-for-byte check, not
    # an artifact of different Python type representations of the same value.
    conn = sqlite3.connect(str(install_a.database_path))
    try:
        recorded_domain_created_at = {
            row[0]: row[1] for row in conn.execute("SELECT slug, created_at FROM domains").fetchall()
        }
    finally:
        conn.close()

    install_a.documents_dir.mkdir(parents=True, exist_ok=True)
    (install_a.documents_dir / "physio-notes.txt").write_text("Physio recommended rest days.\n")

    install_a.domain_summaries_dir.mkdir(parents=True, exist_ok=True)
    (install_a.domain_summaries_dir / "body.md").write_text("# BODY\nKnee stable, training resumed.\n")

    install_a.skills_dir.mkdir(parents=True, exist_ok=True)
    (install_a.skills_dir / "log-weight.md").write_text("# log-weight\nRecord a weight entry.\n")

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors
    if validation.extracted_dir:
        import shutil

        shutil.rmtree(validation.extracted_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Installation B: clean directory, import the export.
    # ------------------------------------------------------------------
    install_b_root = tmp_path / "installation-b"
    install_b = Settings(jarvis_data_dir=str(install_b_root))

    report = restore_archive(export_result.path, install_b)

    assert report.domains_restored == 6
    assert report.conversations_restored == 2
    assert report.messages_restored == 2
    assert report.documents_restored == 1
    assert report.domain_summaries_restored == 1
    assert report.skills_restored == 1
    assert report.schema_revision_after == get_head_revision()

    # Confirm six domains.
    conn = sqlite3.connect(str(install_b.database_path))
    try:
        slugs = {row[0] for row in conn.execute("SELECT slug FROM domains").fetchall()}
        assert slugs == EXPECTED_SLUGS

        # Confirm both conversations and their messages.
        body_id = conn.execute("SELECT id FROM domains WHERE slug='body'").fetchone()[0]
        build_id = conn.execute("SELECT id FROM domains WHERE slug='build'").fetchone()[0]

        body_convs = conn.execute(
            "SELECT id, title FROM conversations WHERE domain_id=?", (body_id,)
        ).fetchall()
        build_convs = conn.execute(
            "SELECT id, title FROM conversations WHERE domain_id=?", (build_id,)
        ).fetchall()

        # Confirm domain isolation.
        assert len(body_convs) == 1
        assert len(build_convs) == 1
        assert body_convs[0][1] == "Knee check-in"
        assert build_convs[0][1] == "Alpha checkpoint"

        # Confirm UUID preservation.
        assert body_convs[0][0] == recorded_body_conv_id
        assert build_convs[0][0] == recorded_build_conv_id

        restored_domain_ids = {
            row[0]: row[1] for row in conn.execute("SELECT slug, id FROM domains").fetchall()
        }
        assert restored_domain_ids == recorded_domain_ids

        # Confirm timestamp preservation.
        restored_created_at = {
            row[0]: row[1] for row in conn.execute("SELECT slug, created_at FROM domains").fetchall()
        }
        for slug in EXPECTED_SLUGS:
            assert restored_created_at[slug] == recorded_domain_created_at[slug]

        body_messages = conn.execute(
            "SELECT content FROM messages WHERE conversation_id=?", (body_convs[0][0],)
        ).fetchall()
        assert body_messages == [("Knee felt fine on today's run.",)]
    finally:
        conn.close()

    # Confirm the document, domain summary, and skill.
    assert (install_b.documents_dir / "physio-notes.txt").read_text() == (
        "Physio recommended rest days.\n"
    )
    assert (install_b.domain_summaries_dir / "body.md").exists()
    assert (install_b.skills_dir / "log-weight.md").exists()

    # Create a new message after restoration to prove the system is writable.
    engine_b = build_engine(install_b.database_url)
    session_factory_b = build_sessionmaker(engine_b)
    with session_factory_b() as session:
        body_conv_row = session.query(Conversation).filter_by(id=recorded_body_conv_id).one()
        new_message = Message(
            conversation_id=body_conv_row.id,
            role="user",
            content="Post-restore check: still writable.",
        )
        session.add(new_message)
        session.commit()
    engine_b.dispose()

    conn = sqlite3.connect(str(install_b.database_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id=?", (recorded_body_conv_id,)
        ).fetchone()[0]
        assert count == 2
    finally:
        conn.close()

    # Export installation B again and verify that archive too.
    export_b_result = create_export(install_b)
    validation_b = validate_archive(export_b_result.path)
    assert validation_b.ok, validation_b.errors
    assert validation_b.manifest["schema_revision"] == get_head_revision()
    if validation_b.extracted_dir:
        import shutil

        shutil.rmtree(validation_b.extracted_dir, ignore_errors=True)


def test_simulated_failed_restore_preserves_existing_target(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine = build_engine(install_a.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
    engine.dispose()

    export_result = create_export(install_a)

    target = Settings(jarvis_data_dir=str(tmp_path / "existing-target"))
    restore_archive(export_result.path, target)
    create_backup(target)  # unrelated local state that must also survive untouched

    original_db_bytes = target.database_path.read_bytes()
    original_backup_files = sorted((target.backups_dir / "daily").iterdir())

    import app.import_service as import_service_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated catastrophic failure mid-restore")

    original_fn = import_service_module.upgrade_database_to_head
    import_service_module.upgrade_database_to_head = _boom
    try:
        with pytest.raises(RestoreError):
            restore_archive(export_result.path, target, confirm_overwrite=True)
    finally:
        import_service_module.upgrade_database_to_head = original_fn

    # The existing target must remain exactly as it was before the failed attempt.
    assert target.database_path.read_bytes() == original_db_bytes
    assert sorted((target.backups_dir / "daily").iterdir()) == original_backup_files
