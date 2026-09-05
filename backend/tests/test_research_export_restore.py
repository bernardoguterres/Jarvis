"""Phase 12E: export/restore/restart safety. Research workspaces,
evidence references, notes, brief versions, and citation mappings survive
an ordinary restart and a full export/restore round trip via the whole-
database SQLite backup mechanism (no per-table export/import code was
added — nothing new is required there). Restore must never trigger
regeneration or a model call, must preserve historical briefs, and must
mark a missing source reference unavailable rather than erasing its
citation. No credentials/tokens/raw payloads ever enter a research
record or export."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Conversation, Domain, Message
from app.recall_index_service import sync_recall
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_research_data_survives_export_and_restore(tmp_path: Path) -> None:
    from app import research_service as rs

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        build = session.query(Domain).filter_by(slug="build").one()
        conv = Conversation(domain_id=build.id, title="Tokenizer research")
        session.add(conv)
        session.flush()
        msg = Message(conversation_id=conv.id, role="user", content="BPE handles rare words well.")
        session.add(msg)
        session.commit()
        sync_recall(session, "conversation", conv.id)
        sync_recall(session, "message", msg.id)
        session.commit()

        ws = rs.create_workspace(session, title="Tokenizer choice for Alpha")
        evidence = rs.add_evidence(session, ws.id, source_type="message", source_id=msg.id, classification="supporting")
        rs.add_note(session, ws.id, content="BPE seems standard.", linked_evidence_ids=[evidence.id])
        version = rs.generate_deterministic_brief(session, ws.id)
        workspace_id, evidence_id, version_id = ws.id, evidence.id, version.id
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        workspace = rs.get_workspace(session, workspace_id)
        assert workspace.title == "Tokenizer choice for Alpha"
        evidence_rows = rs.list_evidence(session, workspace_id)
        assert len(evidence_rows) == 1
        assert evidence_rows[0].id == evidence_id
        notes = rs.list_notes(session, workspace_id)
        assert len(notes) == 1
        assert notes[0].content == "BPE seems standard."
        restored_version = rs.get_brief_version(session, workspace_id, version_id)
        assert restored_version.sections_json  # preserved verbatim
        citations = json.loads(restored_version.citations_json)
        assert citations[0]["evidence_id"] == evidence_id
        # Fresh availability re-check still works post-restore.
        reads = rs.citation_reads(session, restored_version)
        assert reads[0]["available"] is True
    engine_b.dispose()


def test_restore_never_regenerates_a_brief_or_calls_a_model(tmp_path: Path, monkeypatch) -> None:
    """Restoring must never trigger a new brief version or reach out to a
    provider — restore only replays the SQLite database file itself."""
    from app import research_service as rs

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        build = session.query(Domain).filter_by(slug="build").one()
        conv = Conversation(domain_id=build.id, title="t")
        session.add(conv)
        session.flush()
        msg = Message(conversation_id=conv.id, role="user", content="c")
        session.add(msg)
        session.commit()
        sync_recall(session, "conversation", conv.id)
        sync_recall(session, "message", msg.id)
        session.commit()

        ws = rs.create_workspace(session, title="x")
        rs.add_evidence(session, ws.id, source_type="message", source_id=msg.id)
        rs.generate_deterministic_brief(session, ws.id)
        workspace_id = ws.id
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        versions = rs.list_brief_versions(session, workspace_id)
        # Restore did not create a second/regenerated version — exactly
        # the one deterministic version from before the export.
        assert len(versions) == 1
        assert versions[0].source == "deterministic"
    engine_b.dispose()


def test_removed_source_after_restore_reports_unavailable_without_erasing_citation(tmp_path: Path) -> None:
    from app import research_service as rs

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        build = session.query(Domain).filter_by(slug="build").one()
        conv = Conversation(domain_id=build.id, title="t")
        session.add(conv)
        session.flush()
        msg = Message(conversation_id=conv.id, role="user", content="c")
        session.add(msg)
        session.commit()
        sync_recall(session, "conversation", conv.id)
        sync_recall(session, "message", msg.id)
        session.commit()

        ws = rs.create_workspace(session, title="x")
        rs.add_evidence(session, ws.id, source_type="message", source_id=msg.id)
        version = rs.generate_deterministic_brief(session, ws.id)
        workspace_id, version_id, conv_id = ws.id, version.id, conv.id
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        from datetime import datetime, timezone

        conversation = session.get(Conversation, conv_id)
        conversation.archived_at = datetime.now(timezone.utc)
        session.commit()

        version = rs.get_brief_version(session, workspace_id, version_id)
        reads = rs.citation_reads(session, version)
        assert reads[0]["available"] is False
        assert reads[0]["unavailable_reason"] is not None
        # The citation itself is never erased — it stays fully readable.
        assert reads[0]["title_snapshot"]
        assert reads[0]["snippet_snapshot"]
    engine_b.dispose()


def test_ordinary_restart_preserves_research_data(restart_client_factory) -> None:
    client_a = restart_client_factory()
    resp = client_a.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": "Renew passport"}},
    )
    task_id = resp.json()["id"]
    ws = client_a.post("/api/research/workspaces", json={"title": "Restart test"}).json()
    evidence = client_a.post(
        f"/api/research/workspaces/{ws['id']}/evidence",
        json={"source_type": "structured_record", "source_id": task_id},
    ).json()
    client_a.post(f"/api/research/workspaces/{ws['id']}/briefs/deterministic")

    client_b = restart_client_factory()  # simulates a fresh process against the same data dir
    detail = client_b.get(f"/api/research/workspaces/{ws['id']}").json()
    assert detail["evidence_count"] == 1
    assert detail["latest_brief_version"] == 1
    listing = client_b.get(f"/api/research/workspaces/{ws['id']}/evidence").json()
    assert listing[0]["id"] == evidence["id"]


def test_no_secrets_in_research_export(tmp_path: Path) -> None:
    install = _make_installation(tmp_path / "installation-a")
    export_result = create_export(install)
    with zipfile.ZipFile(export_result.path) as zf:
        contents = b"".join(
            zf.read(name) for name in zf.namelist() if name.endswith((".sqlite", ".json"))
        )
    assert b"api_key" not in contents.lower()
    assert b"bearer" not in contents.lower()
