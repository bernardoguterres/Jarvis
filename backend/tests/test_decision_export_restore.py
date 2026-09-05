"""Phase 12F: export/restore/restart safety. Decisions, options, criteria,
assessments, evidence links, factors, brief versions, final versions, and
outcome reviews all survive an ordinary restart and a full export/restore
round trip via the whole-database SQLite backup mechanism (no per-table
export/import code was added — nothing new is required there). Restore
must never trigger regeneration or a model call, must preserve historical
brief/final versions, and must mark a missing source reference
unavailable rather than erasing its citation."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Conversation, Domain, Message
from app.recall_index_service import sync_recall
from app.seed import seed_domains

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_decision_data_survives_export_and_restore(tmp_path: Path) -> None:
    from app import decision_service as ds

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        build = session.query(Domain).filter_by(slug="build").one()
        conv = Conversation(domain_id=build.id, title="Tokenizer notes")
        session.add(conv)
        session.flush()
        msg = Message(conversation_id=conv.id, role="user", content="BPE handles rare words well.")
        session.add(msg)
        session.commit()
        sync_recall(session, "conversation", conv.id)
        sync_recall(session, "message", msg.id)
        session.commit()

        decision = ds.create_decision(session, title="Tokenizer choice for Alpha")
        option = ds.add_option(session, decision.id, name="BPE")
        criterion = ds.add_criterion(session, decision.id, name="Simplicity", weight=4)
        ds.set_assessment(session, decision.id, option_id=option.id, criterion_id=criterion.id, score=5)
        evidence = ds.add_evidence(session, decision.id, source_type="message", source_id=msg.id)
        factor = ds.add_factor(session, decision.id, kind="risk", content="Might need retraining.")
        brief = ds.generate_deterministic_brief(session, decision.id)
        ds.decide(session, decision.id, selected_option_id=option.id, rationale="Simplest and proven.", decision_confidence=4, now=NOW)
        ds.add_outcome_review(session, decision.id, what_happened="Shipped, worked well.", intended_outcome_achieved=True)

        decision_id, option_id, evidence_id, factor_id, brief_id = (
            decision.id, option.id, evidence.id, factor.id, brief.id,
        )
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        decision = ds.get_decision(session, decision_id)
        assert decision.title == "Tokenizer choice for Alpha"
        assert decision.status == "decided"

        options = ds.list_options(session, decision_id)
        assert len(options) == 1 and options[0].id == option_id

        assessments = ds.list_assessments(session, decision_id)
        assert len(assessments) == 1 and assessments[0].score == 5

        evidence_rows = ds.list_evidence(session, decision_id)
        assert len(evidence_rows) == 1 and evidence_rows[0].id == evidence_id
        reads = ds.evidence_read_fields(session, evidence_rows[0])
        assert reads["available"] is True

        factors = ds.list_factors(session, decision_id)
        assert len(factors) == 1 and factors[0].id == factor_id

        restored_brief = ds.get_brief_version(session, decision_id, brief_id)
        assert restored_brief.sections_json  # preserved verbatim
        citations = json.loads(restored_brief.citations_json)
        assert citations[0]["evidence_id"] == evidence_id

        final_versions = ds.list_final_versions(session, decision_id)
        assert len(final_versions) == 1
        assert final_versions[0].rationale == "Simplest and proven."

        reviews = ds.list_outcome_reviews(session, decision_id)
        assert len(reviews) == 1
        assert reviews[0].what_happened == "Shipped, worked well."
    engine_b.dispose()


def test_restore_never_regenerates_a_brief_or_calls_a_model(tmp_path: Path) -> None:
    from app import decision_service as ds

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        decision = ds.create_decision(session, title="x")
        ds.add_option(session, decision.id, name="opt")
        ds.generate_deterministic_brief(session, decision.id)
        decision_id = decision.id
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        versions = ds.list_brief_versions(session, decision_id)
        assert len(versions) == 1
        assert versions[0].source == "deterministic"
    engine_b.dispose()


def test_removed_source_after_restore_reports_unavailable_without_erasing_citation(tmp_path: Path) -> None:
    from app import decision_service as ds

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

        decision = ds.create_decision(session, title="x")
        ds.add_option(session, decision.id, name="opt")
        ds.add_evidence(session, decision.id, source_type="message", source_id=msg.id)
        brief = ds.generate_deterministic_brief(session, decision.id)
        decision_id, brief_id, conv_id = decision.id, brief.id, conv.id
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        conversation = session.get(Conversation, conv_id)
        conversation.archived_at = datetime.now(timezone.utc)
        session.commit()

        version = ds.get_brief_version(session, decision_id, brief_id)
        reads = ds.citation_reads(session, version)
        assert reads[0]["available"] is False
        assert reads[0]["unavailable_reason"] is not None
        assert reads[0]["title_snapshot"]
        assert reads[0]["snippet_snapshot"]
    engine_b.dispose()


def test_ordinary_restart_preserves_decision_data(restart_client_factory) -> None:
    client_a = restart_client_factory()
    d = client_a.post("/api/decisions", json={"title": "Restart test"}).json()
    option = client_a.post(f"/api/decisions/{d['id']}/options", json={"name": "opt"}).json()
    client_a.post(f"/api/decisions/{d['id']}/briefs/deterministic")

    client_b = restart_client_factory()  # simulates a fresh process against the same data dir
    detail = client_b.get(f"/api/decisions/{d['id']}").json()
    assert detail["option_count"] == 1
    assert detail["latest_brief_version"] == 1
    options = client_b.get(f"/api/decisions/{d['id']}/options").json()
    assert options[0]["id"] == option["id"]


def test_no_secrets_in_decision_export(tmp_path: Path) -> None:
    install = _make_installation(tmp_path / "installation-a")
    export_result = create_export(install)
    with zipfile.ZipFile(export_result.path) as zf:
        contents = b"".join(zf.read(name) for name in zf.namelist() if name.endswith((".sqlite", ".json")))
    assert b"api_key" not in contents.lower()
    assert b"bearer" not in contents.lower()
