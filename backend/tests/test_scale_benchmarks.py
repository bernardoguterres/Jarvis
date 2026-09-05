"""V1 reliability audit — scale testing (workstream 4).

Generates a fictional dataset representing roughly one year of genuine,
if fairly heavy, personal use across all six domains, then benchmarks the
operations named in the audit brief: startup, FTS retrieval, context
construction, conversation loading, export, validation, and an isolated
restore. Never real user data — every string here is synthetic.

This is a *reasonableness* check for a single-user local SQLite app, not a
stress test for a multi-tenant service: the volumes below are deliberately
generous compared to Bernardo's actual expected usage, and the timing
bounds are generous upper bounds (an order of magnitude beyond what a
personal machine should ever need for these operations), chosen to catch a
genuine algorithmic regression (an accidental O(n^2) somewhere, a missing
index) without being flaky on a slower CI/container machine. If a bound is
ever hit, that is itself the finding — see docs/DECISIONS.md D83/D84 for
the actual measurements recorded from the run that produced this file.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import context_builder, domain_summary_service, export_service, fts_service, import_service, memory_service
from app.config import Settings
from app.database import build_sessionmaker
from app.migration_info import upgrade_database_to_head
from app.models import Conversation, Domain, Message
from app.models_actions import ActionAuditEvent, ActionProposal, Skill, SkillVersion
from app.models_integrations import Document, DocumentChunk
from app.models_routines import RoutineRun
from app.seed import seed_domains
from app.structured_record_service import create_structured_record

# --- Volume targets: "a genuinely used year," not a stress test ------------
CONVERSATIONS_PER_DOMAIN = 40
MESSAGES_PER_CONVERSATION = 8
DOMAIN_MEMORIES_PER_DOMAIN = 45
GLOBAL_MEMORIES = 40
RECORDS_PER_DOMAIN = 60
SUMMARY_EDITS_PER_DOMAIN = 12
ACTION_PROPOSALS = 150
ROUTINE_RUNS_PER_TYPE = 200
SKILLS_COUNT = 10
DOCUMENTS_COUNT = 15
CHUNKS_PER_DOCUMENT = 8

RECORD_PAYLOADS = {
    "body": ("body_weight", lambda i: {"kilograms": round(70 + (i % 20) * 0.3, 1)}),
    "mind": ("mind_checkin", lambda i: {"mood": ["good", "okay", "low", "great"][i % 4], "note": f"Check-in note #{i}, a fictional day-in-the-life entry of moderate length for realism."}),
    "people": ("people_interaction", lambda i: {"person": f"Friend {i % 12}", "note": f"Fictional catch-up note #{i} about a call or visit, moderate length for realism."}),
    "path": ("path_deadline", lambda i: {"title": f"Fictional application deadline #{i}", "due_date": "2026-12-01", "note": "Synthetic deadline note."}),
    "build": ("build_checkpoint", lambda i: {"project": f"Fictional project {i % 5}", "summary": f"Checkpoint #{i}: synthetic progress summary of moderate length for a realistic personal engineering log entry."}),
    "life": ("life_task", lambda i: {"title": f"Fictional task #{i}", "due_date": "2026-12-01", "note": "Synthetic task note."}),
}

BENCHMARK_REPORT: dict[str, object] = {}


@pytest.fixture(scope="module")
def scale_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    """A single, module-scoped, isolated JARVIS_DATA_DIR populated once and
    reused read-mostly across every benchmark in this file — generating a
    year of data is itself expensive and is not what's being timed."""
    data_dir = tmp_path_factory.mktemp("jarvis-scale")
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


@pytest.fixture(scope="module")
def scale_session(scale_settings: Settings) -> Session:
    from app.database import build_engine

    engine = build_engine(scale_settings.database_url)
    session_factory = build_sessionmaker(engine)
    session = session_factory()
    seed_domains(session)
    _generate_dataset(session, scale_settings)
    yield session
    session.close()
    engine.dispose()


def _generate_dataset(session: Session, settings: Settings) -> None:
    start = time.monotonic()
    domains = {d.slug: d for d in session.query(Domain).all()}
    base_time = datetime.now(timezone.utc) - timedelta(days=365)

    # Global memories (real service call — must go through FTS indexing).
    for i in range(GLOBAL_MEMORIES):
        memory_service.create_memory(
            session, scope="global", domain_id=None, kind="fact",
            title=f"Global fact #{i}",
            content=f"Fictional global profile fact #{i}, a realistic sentence-length entry about a stable preference or life detail.",
        )

    for slug, domain in domains.items():
        # Conversations + messages.
        for c in range(CONVERSATIONS_PER_DOMAIN):
            conv = Conversation(domain_id=domain.id, title=f"{slug} conversation {c}")
            session.add(conv)
            session.flush()
            for m in range(MESSAGES_PER_CONVERSATION):
                role = "user" if m % 2 == 0 else "assistant"
                session.add(
                    Message(
                        conversation_id=conv.id,
                        role=role,
                        content=f"Fictional {role} message #{m} in {slug} conversation #{c} — a realistic sentence-length turn.",
                        created_at=base_time + timedelta(days=c * 9, hours=m),
                        model_used="gpt-5.6-terra" if role == "assistant" else None,
                    )
                )
        session.commit()

        # Domain memories (real service call for FTS indexing).
        for i in range(DOMAIN_MEMORIES_PER_DOMAIN):
            memory_service.create_memory(
                session, scope="domain", domain_id=domain.id, kind="fact",
                title=f"{slug} memory #{i}",
                content=f"Fictional {slug}-scoped memory #{i}, a realistic sentence-length entry a real year of use would plausibly accumulate.",
            )

        # Structured records (real validated service call).
        record_type, payload_fn = RECORD_PAYLOADS[slug]
        for i in range(RECORDS_PER_DOMAIN):
            create_structured_record(
                session, domain_id=domain.id, record_type=record_type,
                occurred_at=base_time + timedelta(days=i * 6), payload=payload_fn(i),
            )

        # Domain summary — several real edited versions over the year.
        for i in range(SUMMARY_EDITS_PER_DOMAIN):
            domain_summary_service.set_domain_summary(
                session, domain.id,
                f"Fictional {slug} summary, revision {i} — a realistic paragraph-length rolling summary of the domain's state at this point in the year.",
            )

    # Action proposals + audit events — bulk ORM inserts (proposal creation
    # itself isn't a benchmarked operation here; volume matters for export
    # size, not for exercising action_service's own logic, which has its
    # own dedicated tests).
    statuses = ["succeeded", "succeeded", "succeeded", "denied", "failed", "expired"]
    domain_list = list(domains.values())
    for i in range(ACTION_PROPOSALS):
        status = statuses[i % len(statuses)]
        proposal = ActionProposal(
            capability_id="memory.create",
            domain_id=domain_list[i % len(domain_list)].id,
            arguments_json=json.dumps({"scope": "domain", "kind": "fact", "title": f"T{i}", "content": "c"}),
            reason=f"Fictional proposal reason #{i}.",
            expected_effect=f"Create a memory titled 'T{i}'.",
            payload_digest=hashlib.sha256(f"digest-{i}".encode()).hexdigest(),
            status=status,
            source="manual_proposal",
            created_at=base_time + timedelta(days=i * 2),
        )
        session.add(proposal)
        session.flush()
        session.add(ActionAuditEvent(action_proposal_id=proposal.id, event_type="proposed"))
        session.add(ActionAuditEvent(action_proposal_id=proposal.id, event_type=status))
    session.commit()

    # Skills.
    for i in range(SKILLS_COUNT):
        skill = Skill(
            slug=f"fictional-skill-{i}", name=f"Fictional skill {i}",
            description="A synthetic skill for scale testing.",
            domain_id=domain_list[i % len(domain_list)].id, status="active" if i % 3 else "draft",
        )
        session.add(skill)
        session.flush()
        version = SkillVersion(
            skill_id=skill.id, version_number=1, name=skill.name, description=skill.description,
            workflow_steps_json=json.dumps([{"capability_id": "memory.create", "description": "Log a fact"}]),
        )
        session.add(version)
        session.flush()
        skill.current_version_id = version.id
    session.commit()

    # Routine runs — a year of daily/weekly cadence.
    for routine_type in ("morning_briefing", "evening_checkin", "weekly_review"):
        for i in range(ROUTINE_RUNS_PER_TYPE):
            session.add(
                RoutineRun(
                    routine_type=routine_type,
                    trigger="scheduled",
                    started_at=base_time + timedelta(days=i),
                    completed_at=base_time + timedelta(days=i, seconds=2),
                    outcome="succeeded",
                    output_json=json.dumps({"sections": [{"title": "Today", "lines": [{"text": f"Fictional line {i}", "source_ref": f"record:{i:08x}"}]}]}),
                    responses_json="{}",
                    selected_domains_json="[]",
                )
            )
    session.commit()

    # Documents + chunks — a few real small files on disk too, for realism.
    documents_dir = settings.data_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    for i in range(DOCUMENTS_COUNT):
        content = f"Fictional document #{i} content.\n" * 20
        sha = hashlib.sha256(content.encode()).hexdigest()
        (documents_dir / f"{sha}.txt").write_text(content)
        doc = Document(
            domain_id=domain_list[i % len(domain_list)].id,
            original_filename=f"fictional-doc-{i}.txt",
            stored_relative_path=f"documents/{sha}.txt",
            mime_type="text/plain", sha256=sha, size_bytes=len(content), status="ready",
        )
        session.add(doc)
        session.flush()
        for c in range(CHUNKS_PER_DOCUMENT):
            session.add(
                DocumentChunk(document_id=doc.id, chunk_index=c, content=f"Fictional chunk #{c} of document #{i}.")
            )
    session.commit()

    BENCHMARK_REPORT["generation_seconds"] = round(time.monotonic() - start, 2)


def _db_size_mb(settings: Settings) -> float:
    return settings.database_path.stat().st_size / (1024 * 1024)


def test_report_dataset_scale_and_database_size(scale_session: Session, scale_settings: Settings) -> None:
    """Not a pass/fail benchmark — records what was actually generated and
    how large the resulting database is, so a human reviewing this file's
    output (`pytest -s`) can judge scale directly."""
    counts = {
        "conversations": scale_session.query(Conversation).count(),
        "messages": scale_session.query(Message).count(),
        "action_proposals": scale_session.query(ActionProposal).count(),
        "routine_runs": scale_session.query(RoutineRun).count(),
        "documents": scale_session.query(Document).count(),
        "document_chunks": scale_session.query(DocumentChunk).count(),
    }
    BENCHMARK_REPORT["row_counts"] = counts
    BENCHMARK_REPORT["database_size_mb"] = round(_db_size_mb(scale_settings), 2)
    print("\n--- Scale benchmark dataset ---")
    print(json.dumps(BENCHMARK_REPORT, indent=2))
    assert counts["messages"] > 1000
    assert BENCHMARK_REPORT["database_size_mb"] < 200  # sanity: not accidentally unbounded


def test_startup_cold_engine_and_first_query_completes_quickly(scale_settings: Settings) -> None:
    """Approximates cold "app startup" cost against the full-scale
    database: building a fresh engine/session and running the first real
    query (domain listing), the same shape of work `main.py`'s lifespan
    does before the app can serve its first request."""
    from app.database import build_engine

    start = time.monotonic()
    engine = build_engine(scale_settings.database_url)
    session_factory = build_sessionmaker(engine)
    with session_factory() as session:
        domains = session.query(Domain).all()
    elapsed = time.monotonic() - start
    engine.dispose()
    BENCHMARK_REPORT["startup_seconds"] = round(elapsed, 4)
    assert len(domains) == 6
    assert elapsed < 2.0, f"cold engine + first query took {elapsed:.2f}s against a full-scale database"


def test_fts_retrieval_stays_fast_at_full_memory_volume(scale_session: Session) -> None:
    start = time.monotonic()
    results = fts_service.search_memory_fts(scale_session, "fictional memory", limit=20)
    elapsed = time.monotonic() - start
    BENCHMARK_REPORT["fts_search_seconds"] = round(elapsed, 4)
    assert len(results) > 0
    assert elapsed < 1.0, f"FTS search took {elapsed:.2f}s at full memory volume ({GLOBAL_MEMORIES + 6 * DOMAIN_MEMORIES_PER_DOMAIN} memories)"


def test_context_construction_stays_fast_with_a_full_years_history(scale_session: Session) -> None:
    body = scale_session.query(Domain).filter_by(slug="body").one()
    conv = scale_session.query(Conversation).filter_by(domain_id=body.id).first()
    assert conv is not None

    start = time.monotonic()
    package = context_builder.build_context(
        scale_session, conversation=conv, domain=body, additional_domain_ids=[],
        query_text="fictional weight and symptom entries this year", max_recent_messages=20,
    )
    elapsed = time.monotonic() - start
    BENCHMARK_REPORT["context_construction_seconds"] = round(elapsed, 4)
    assert len(package.system_prompt) > 0
    assert elapsed < 1.5, f"context construction took {elapsed:.2f}s against a full year of BODY data"


def test_conversation_loading_stays_fast_with_many_conversations_and_messages(scale_session: Session) -> None:
    from sqlalchemy import select

    body = scale_session.query(Domain).filter_by(slug="body").one()

    start = time.monotonic()
    conversations = scale_session.execute(
        select(Conversation).where(Conversation.domain_id == body.id).order_by(Conversation.created_at.desc())
    ).scalars().all()
    list_elapsed = time.monotonic() - start

    start = time.monotonic()
    messages = scale_session.execute(
        select(Message).where(Message.conversation_id == conversations[0].id).order_by(Message.created_at)
    ).scalars().all()
    load_elapsed = time.monotonic() - start

    BENCHMARK_REPORT["conversation_list_seconds"] = round(list_elapsed, 4)
    BENCHMARK_REPORT["message_load_seconds"] = round(load_elapsed, 4)
    assert len(conversations) == CONVERSATIONS_PER_DOMAIN
    assert len(messages) == MESSAGES_PER_CONVERSATION
    assert list_elapsed < 1.0
    assert load_elapsed < 0.5


def test_export_validate_and_isolated_restore_stay_reasonable_at_full_scale(
    scale_settings: Settings, scale_session: Session, tmp_path: Path
) -> None:
    """The full pipeline the audit brief names: export, validate, and an
    isolated restore, all timed and sized against the full-scale dataset."""
    scale_session.close()  # release the write lock before export's own connection

    start = time.monotonic()
    export_result = export_service.create_export(scale_settings)
    export_elapsed = time.monotonic() - start
    archive_path = export_result.path
    archive_size_mb = archive_path.stat().st_size / (1024 * 1024)

    start = time.monotonic()
    validation = import_service.validate_archive(archive_path)
    validate_elapsed = time.monotonic() - start
    assert validation.ok, validation.errors

    restore_target = tmp_path / "restored"
    restore_target.mkdir()
    target_settings = Settings(jarvis_data_dir=str(restore_target))
    start = time.monotonic()
    restore_result = import_service.restore_archive(archive_path, target_settings)
    restore_elapsed = time.monotonic() - start

    BENCHMARK_REPORT["export_seconds"] = round(export_elapsed, 2)
    BENCHMARK_REPORT["archive_size_mb"] = round(archive_size_mb, 2)
    BENCHMARK_REPORT["validate_seconds"] = round(validate_elapsed, 2)
    BENCHMARK_REPORT["restore_seconds"] = round(restore_elapsed, 2)
    print("\n--- Export/restore benchmark ---")
    print(json.dumps(BENCHMARK_REPORT, indent=2))

    assert restore_result.domains_restored == 6
    assert restore_result.conversations_restored == CONVERSATIONS_PER_DOMAIN * 6
    assert export_elapsed < 15.0, f"export took {export_elapsed:.2f}s at full scale"
    assert validate_elapsed < 10.0, f"validation took {validate_elapsed:.2f}s at full scale"
    assert restore_elapsed < 20.0, f"restore took {restore_elapsed:.2f}s at full scale"
