"""Phase 4 round-trip: export/import must carry memories, versions,
supersession relationships, domain summaries, structured records, and
context snapshots — and the FTS index must be rebuildable after restore
(never trusted as authoritative on its own).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import domain_summary_service, memory_service, structured_record_service
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.fts_service import rebuild_fts, search_memory_fts
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import AgentRun, Conversation, Domain, Message
from app.models_memory import ContextSnapshot, MemoryItem, MemoryVersion
from app.seed import seed_domains
from datetime import datetime, timezone


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_phase4_data_survives_export_and_restore(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    session_factory_a = build_sessionmaker(engine_a)

    with session_factory_a() as session:
        seed_domains(session)
        body = session.query(Domain).filter_by(slug="body").one()

        global_item = memory_service.create_memory(
            session, scope="global", domain_id=None, kind="preference",
            title="Preferred name", content="Call him Bernardo.",
        )
        domain_item = memory_service.create_memory(
            session, scope="domain", domain_id=body.id, kind="health_context",
            title="Knee issue", content="Original knee note.",
        )
        memory_service.edit_memory(session, domain_item.id, content="Updated knee note.")

        old_item = memory_service.create_memory(
            session, scope="global", domain_id=None, kind="fact", title="Old fact", content="outdated",
        )
        new_item = memory_service.supersede_memory(
            session, old_item.id, title="New fact", content="corrected",
        )

        domain_summary_service.set_domain_summary(session, body.id, "First summary.")
        domain_summary_service.set_domain_summary(session, body.id, "Second summary.")

        record = structured_record_service.create_structured_record(
            session, domain_id=body.id, record_type="body_weight",
            occurred_at=datetime.now(timezone.utc), payload={"kilograms": 78.5},
        )

        conv = Conversation(domain_id=body.id, title="Knee chat")
        session.add(conv)
        session.flush()
        user_msg = Message(conversation_id=conv.id, role="user", content="hi")
        session.add(user_msg)
        session.flush()
        run = AgentRun(
            conversation_id=conv.id, user_message_id=user_msg.id, provider="fake",
            model="fake-model", status="succeeded", idempotency_key="k1",
        )
        session.add(run)
        session.flush()
        session.add(
            ContextSnapshot(
                agent_run_id=run.id, active_domain_id=body.id,
                additional_domain_ids_json="[]", global_memory_version_ids_json="[]",
                domain_memory_version_ids_json="[]", domain_summary_version_ids_json="[]",
                structured_record_ids_json="[]", recent_message_ids_json="[]",
                retrieval_query="hi", retrieval_reasons_json="[]", estimated_context_chars=42,
            )
        )
        session.commit()

        recorded = {
            "global_item_id": global_item.id,
            "global_v1_id": global_item.current_version_id,
            "domain_item_id": domain_item.id,
            "new_item_id": new_item.id,
            "old_item_id": old_item.id,
            "record_id": record.id,
            "run_id": run.id,
        }
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors
    if validation.extracted_dir:
        import shutil

        shutil.rmtree(validation.extracted_dir, ignore_errors=True)

    install_b = Settings(jarvis_data_dir=str(tmp_path / "installation-b"))
    restore_archive(export_result.path, install_b)

    conn = sqlite3.connect(str(install_b.database_path))
    try:
        # Global + domain memories present, with full version history.
        titles = {r[0] for r in conn.execute("SELECT title FROM memory_items").fetchall()}
        assert "Preferred name" in titles
        assert "New fact" in titles

        domain_versions = conn.execute(
            "SELECT COUNT(*) FROM memory_versions WHERE memory_item_id=?",
            (recorded["domain_item_id"],),
        ).fetchone()[0]
        assert domain_versions == 2  # original + edited

        # Supersession relationship preserved.
        old_row = conn.execute(
            "SELECT status, superseded_by_id FROM memory_items WHERE id=?",
            (recorded["old_item_id"],),
        ).fetchone()
        assert old_row == ("archived", recorded["new_item_id"])

        # Domain summary versions preserved.
        summary_versions = conn.execute("SELECT COUNT(*) FROM domain_summary_versions").fetchone()[0]
        assert summary_versions == 2

        # Structured record preserved.
        record_row = conn.execute(
            "SELECT record_type FROM structured_records WHERE id=?", (recorded["record_id"],)
        ).fetchone()
        assert record_row == ("body_weight",)

        # Context snapshot preserved.
        snapshot_row = conn.execute(
            "SELECT retrieval_query FROM context_snapshots WHERE agent_run_id=?", (recorded["run_id"],)
        ).fetchone()
        assert snapshot_row == ("hi",)
    finally:
        conn.close()

    # FTS must be rebuildable after restore — never trusted as-is.
    engine_b = build_engine(install_b.database_url)
    with build_sessionmaker(engine_b)() as session:
        count = rebuild_fts(session)
        assert count >= 2  # global "Preferred name" + "New fact" + domain knee memory (active ones)
        hits = search_memory_fts(session, "knee", domain_ids=[
            session.query(Domain).filter_by(slug="body").one().id
        ])
        assert recorded["domain_item_id"] in [h[0] for h in hits]
    engine_b.dispose()
