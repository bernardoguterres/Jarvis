"""V1 durability pass — realistic multi-year scale (D85).

Complements `test_scale_benchmarks.py` (a one-year, ~2,500-row dataset built
through the real service layer, which already validates the write path
itself at moderate scale) with a materially larger, 3-5-year, ~50,000-100,000
-row dataset spanning every table the durability-pass brief names, built via
efficient bulk inserts (this file's purpose is read/query performance at
volume, not re-validating the write path — that's already covered) and
benchmarks every operation named in the brief. Fictional data only.

Thresholds are defined *before* the numbers are seen (see the constants
below), as generous personal-app upper bounds — an order of magnitude past
what a MacBook Pro M2 Pro should ever need for a single user's own SQLite
database. If a threshold is genuinely breached, that is the finding to fix;
hitting a number well inside a bound is not itself grounds to "optimize
away" milliseconds. See docs/DECISIONS.md D85 for the actual measurements
this run produced and the disposition (no code change was needed).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app import context_builder, export_service, fts_service, import_service
from app.config import Settings
from app.database import build_sessionmaker
from app.document_fts_service import upsert_document_chunk_fts
from app.migration_info import upgrade_database_to_head
from app.models import AgentRun, Conversation, Domain, Message
from app.models_actions import ActionAuditEvent, ActionProposal, Skill, SkillVersion
from app.models_integrations import (
    CalendarCalendar,
    CalendarEventCache,
    Document,
    DocumentChunk,
    GoogleHealthDailySummary,
    GoogleHealthSession,
    IntegrationConnection,
)
from app.models_memory import ContextSnapshot, DomainSummary, DomainSummaryVersion, MemoryItem, MemoryVersion, StructuredRecord
from app.models_routines import RoutineRun
from app.models_scheduler import IntegrationSyncRun
from app.seed import seed_domains

YEARS = 5
DAYS = 365 * YEARS

# --- Reasonable-personal-app thresholds, fixed BEFORE the run (seconds) ---
THRESHOLDS = {
    "dataset_generation": 180.0,   # a one-time fixture build, not a user-facing op
    "cold_startup": 3.0,
    "fts_search": 1.5,
    "context_construction": 2.0,
    "conversation_list": 1.5,
    "message_load": 1.0,
    "integration_history_read": 1.0,
    "routine_history_read": 1.0,
    "export": 60.0,
    "validate": 30.0,
    "restore": 90.0,
}
MAX_DATABASE_SIZE_MB = 500.0  # a personal single-user app should never approach this

BENCHMARK_REPORT: dict[str, object] = {}


def _uuid() -> str:
    return str(uuid.uuid4())


def _bulk(session: Session, model, rows: list[dict], batch_size: int = 5000) -> None:
    for i in range(0, len(rows), batch_size):
        session.execute(insert(model), rows[i : i + batch_size])
    session.commit()


@pytest.fixture(scope="module")
def multiyear_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    data_dir = tmp_path_factory.mktemp("jarvis-multiyear")
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


@pytest.fixture(scope="module")
def multiyear_session(multiyear_settings: Settings) -> Session:
    from app.database import build_engine

    engine = build_engine(multiyear_settings.database_url)
    session_factory = build_sessionmaker(engine)
    session = session_factory()
    seed_domains(session)
    _generate(session, multiyear_settings)
    yield session
    session.close()
    engine.dispose()


def _generate(session: Session, settings: Settings) -> None:
    start = time.monotonic()
    base_time = datetime.now(timezone.utc) - timedelta(days=DAYS)
    domains = {d.slug: d.id for d in session.query(Domain).all()}
    domain_ids = list(domains.values())
    total_rows = 0

    # --- Conversations + messages (+ a subset of agent_runs/context_snapshots) ---
    CONVERSATIONS_PER_DOMAIN = 260  # ~52/year/domain
    MESSAGES_PER_CONVERSATION = 12
    conv_rows, msg_rows, run_rows, snap_rows = [], [], [], []
    for slug, domain_id in domains.items():
        for c in range(CONVERSATIONS_PER_DOMAIN):
            conv_id = _uuid()
            created = base_time + timedelta(days=int(DAYS * c / CONVERSATIONS_PER_DOMAIN))
            conv_rows.append({"id": conv_id, "domain_id": domain_id, "title": f"{slug} conversation {c}", "created_at": created, "updated_at": created, "archived_at": None})
            first_user_id = None
            first_assistant_id = None
            for m in range(MESSAGES_PER_CONVERSATION):
                role = "user" if m % 2 == 0 else "assistant"
                msg_id = _uuid()
                msg_rows.append({
                    "id": msg_id, "conversation_id": conv_id, "role": role,
                    "content": f"Fictional {role} message #{m} in {slug} conversation #{c} — realistic sentence length.",
                    "created_at": created + timedelta(hours=m), "model_used": "gpt-5.6-terra" if role == "assistant" else None,
                })
                if role == "user" and first_user_id is None:
                    first_user_id = msg_id
                if role == "assistant" and first_assistant_id is None:
                    first_assistant_id = msg_id
            # One agent_run + context_snapshot per conversation — a real,
            # audited turn, not every message (matches real usage: not
            # every note is sent to Jarvis).
            if first_user_id and first_assistant_id:
                run_id = _uuid()
                run_rows.append({
                    "id": run_id, "conversation_id": conv_id, "user_message_id": first_user_id,
                    "assistant_message_id": first_assistant_id, "provider": "hermes", "model": "gpt-5.6-terra",
                    "status": "succeeded", "started_at": created, "completed_at": created + timedelta(seconds=2),
                    "latency_ms": 1800, "input_tokens": 400, "output_tokens": 120, "total_tokens": 520,
                    "external_run_id": None, "error_code": None, "error_summary": None, "idempotency_key": _uuid(),
                })
                snap_rows.append({
                    "id": _uuid(), "agent_run_id": run_id, "active_domain_id": domain_id,
                    "additional_domain_ids_json": "[]", "global_memory_version_ids_json": "[]",
                    "domain_memory_version_ids_json": "[]", "domain_summary_version_ids_json": "[]",
                    "structured_record_ids_json": "[]", "recent_message_ids_json": json.dumps([first_user_id]),
                    "retrieval_query": "fictional query", "retrieval_reasons_json": "[]",
                    "estimated_context_chars": 1200, "document_chunk_ids_json": "[]",
                    "calendar_event_ids_json": "[]", "google_health_summary_ids_json": "[]",
                    "created_at": created,
                })
    _bulk(session, Conversation, conv_rows)
    _bulk(session, Message, msg_rows)
    _bulk(session, AgentRun, run_rows)
    _bulk(session, ContextSnapshot, snap_rows)
    total_rows += len(conv_rows) + len(msg_rows) + len(run_rows) + len(snap_rows)

    # --- Memories (items + versions) + FTS, bulk (not the real service call —
    # already validated at moderate scale in test_scale_benchmarks.py) ---
    # MemoryItem.current_version_id and MemoryVersion.memory_item_id are
    # mutually referencing FKs — inserted with current_version_id=NULL
    # first, then versions, then a bulk UPDATE sets current_version_id
    # (mirrors how memory_service.create_memory itself sequences this in
    # two real statements, just batched for volume here).
    MEMORIES_PER_DOMAIN = 450
    item_rows, version_rows, fts_rows, item_version_updates = [], [], [], []
    for slug, domain_id in domains.items():
        for i in range(MEMORIES_PER_DOMAIN):
            item_id = _uuid()
            version_id = _uuid()
            title = f"{slug} memory #{i}"
            content = f"Fictional {slug}-scoped memory #{i}, a realistic sentence-length entry a multi-year real history would plausibly accumulate."
            created = base_time + timedelta(days=int(DAYS * i / MEMORIES_PER_DOMAIN))
            item_rows.append({
                "id": item_id, "scope": "domain", "domain_id": domain_id, "kind": "fact", "title": title,
                "status": "active", "importance": 3, "confidence": 1.0, "sensitivity": "normal",
                "event_date": None, "created_at": created, "updated_at": created,
                "current_version_id": None, "supersedes_id": None, "superseded_by_id": None,
            })
            version_rows.append({
                "id": version_id, "memory_item_id": item_id, "version_number": 1, "title": title,
                "kind": "fact", "content": content, "importance": 3, "confidence": 1.0, "sensitivity": "normal",
                "event_date": None, "change_reason": None, "source": "explicit_remember", "created_at": created,
            })
            item_version_updates.append({"item_id": item_id, "version_id": version_id})
            fts_rows.append({"memory_item_id": item_id, "scope": "domain", "domain_id": domain_id, "title": title, "content": content})
    # Global memories too.
    for i in range(200):
        item_id, version_id = _uuid(), _uuid()
        title, content = f"Global fact #{i}", f"Fictional global profile fact #{i}, a realistic entry."
        created = base_time + timedelta(days=int(DAYS * i / 200))
        item_rows.append({"id": item_id, "scope": "global", "domain_id": None, "kind": "fact", "title": title, "status": "active", "importance": 3, "confidence": 1.0, "sensitivity": "normal", "event_date": None, "created_at": created, "updated_at": created, "current_version_id": None, "supersedes_id": None, "superseded_by_id": None})
        version_rows.append({"id": version_id, "memory_item_id": item_id, "version_number": 1, "title": title, "kind": "fact", "content": content, "importance": 3, "confidence": 1.0, "sensitivity": "normal", "event_date": None, "change_reason": None, "source": "explicit_remember", "created_at": created})
        item_version_updates.append({"item_id": item_id, "version_id": version_id})
        fts_rows.append({"memory_item_id": item_id, "scope": "global", "domain_id": None, "title": title, "content": content})
    _bulk(session, MemoryItem, item_rows)
    _bulk(session, MemoryVersion, version_rows)
    update_stmt = text("UPDATE memory_items SET current_version_id = :version_id WHERE id = :item_id")
    for i in range(0, len(item_version_updates), 5000):
        session.execute(update_stmt, item_version_updates[i : i + 5000])
    session.commit()
    fts_insert = text(
        "INSERT INTO memory_fts (memory_item_id, scope, domain_id, title, content) "
        "VALUES (:memory_item_id, :scope, :domain_id, :title, :content)"
    )
    for i in range(0, len(fts_rows), 5000):
        session.execute(fts_insert, fts_rows[i : i + 5000])
    session.commit()
    total_rows += len(item_rows) + len(version_rows)

    # --- Domain summaries (a handful of versions each, realistic) ---
    # Same mutual-FK ordering as memories above.
    summary_rows, summary_version_rows, summary_updates = [], [], []
    for slug, domain_id in domains.items():
        summary_id = _uuid()
        edits = 25  # roughly monthly over 5 years, occasionally skipped
        last_version_id = None
        for v in range(1, edits + 1):
            version_id = _uuid()
            summary_version_rows.append({
                "id": version_id, "domain_summary_id": summary_id, "version_number": v,
                "content": f"Fictional {slug} summary, revision {v} over a multi-year history.",
                "source": "manual", "created_at": base_time + timedelta(days=int(DAYS * v / edits)),
            })
            last_version_id = version_id
        summary_rows.append({"id": summary_id, "domain_id": domain_id, "current_version_id": None})
        summary_updates.append({"summary_id": summary_id, "version_id": last_version_id})
    _bulk(session, DomainSummary, summary_rows)
    _bulk(session, DomainSummaryVersion, summary_version_rows)
    session.execute(text("UPDATE domain_summaries SET current_version_id = :version_id WHERE id = :summary_id"), summary_updates)
    session.commit()
    total_rows += len(summary_rows) + len(summary_version_rows)

    # --- Structured records (direct rows — payload shapes mirror
    # structured_record_service's validated schema, but bulk-inserted since
    # write-path validation is already covered elsewhere). ---
    RECORD_TYPE_BY_SLUG = {"body": "body_weight", "mind": "mind_checkin", "people": "people_interaction", "path": "path_deadline", "build": "build_checkpoint", "life": "life_task"}
    record_rows = []
    RECORDS_PER_DOMAIN = 650
    for slug, domain_id in domains.items():
        record_type = RECORD_TYPE_BY_SLUG[slug]
        for i in range(RECORDS_PER_DOMAIN):
            record_rows.append({
                "id": _uuid(), "domain_id": domain_id, "record_type": record_type,
                "occurred_at": base_time + timedelta(days=int(DAYS * i / RECORDS_PER_DOMAIN)),
                "payload_json": json.dumps({"note": f"Fictional {record_type} entry #{i}"}),
                "source_message_id": None, "sensitivity": "normal",
                "created_at": base_time + timedelta(days=int(DAYS * i / RECORDS_PER_DOMAIN)), "archived_at": None,
            })
    _bulk(session, StructuredRecord, record_rows)
    total_rows += len(record_rows)

    # --- Google Health: daily summaries (one per day, 5 years) + sessions ---
    gh_summary_rows = []
    for i in range(DAYS):
        d = (base_time + timedelta(days=i)).date()
        gh_summary_rows.append({
            "id": _uuid(), "date": d, "steps": 4000 + (i % 6000), "distance_km": round(3 + (i % 10) * 0.4, 2),
            "floors": i % 20, "active_zone_minutes": i % 60, "active_calories_kcal": 300.0 + (i % 200),
            "calories_out": 2000.0 + (i % 500), "resting_heart_rate": 50 + (i % 20),
            "heart_rate_avg_bpm": 65.0 + (i % 15), "heart_rate_min_bpm": 48.0, "heart_rate_max_bpm": 150.0,
            "hrv_daily_rmssd_ms": 40.0 + (i % 30), "oxygen_saturation_avg_percent": 96.0 + (i % 3),
            "respiratory_rate_breaths_per_min": 14.0, "vo2_max": 42.0, "weight_kg": 75.0 + (i % 10) * 0.2,
            "weight_source": "smart_scale", "body_fat_percent": None, "blood_glucose_mg_dl": None,
            "sleep_duration_ms": 25000000 + (i % 5000000), "sleep_minutes_asleep": 400 + (i % 60),
            "sleep_efficiency": 88, "sleep_type": "stages", "fetched_at": base_time + timedelta(days=i),
        })
    _bulk(session, GoogleHealthDailySummary, gh_summary_rows)

    gh_session_rows = []
    for i in range(DAYS):
        night = base_time + timedelta(days=i, hours=23)
        gh_session_rows.append({
            "id": _uuid(), "session_type": "sleep", "external_id": f"sleep-{i}",
            "start_time": night, "end_time": night + timedelta(hours=7), "activity_type": None,
            "calories_kcal": None, "distance_km": None, "average_heart_rate_bpm": None,
            "minutes_asleep": 400, "minutes_awake": 20, "stages_json": None,
            "source_platform": "Pixel Watch", "source_device": "Pixel Watch 3", "fetched_at": night,
        })
        if i % 2 == 0:  # exercise roughly every other day
            morning = base_time + timedelta(days=i, hours=7)
            gh_session_rows.append({
                "id": _uuid(), "session_type": "exercise", "external_id": f"exercise-{i}",
                "start_time": morning, "end_time": morning + timedelta(minutes=45), "activity_type": "strength_training",
                "calories_kcal": 300.0, "distance_km": None, "average_heart_rate_bpm": 120.0,
                "minutes_asleep": None, "minutes_awake": None, "stages_json": None,
                "source_platform": "Pixel Watch", "source_device": "Pixel Watch 3", "fetched_at": morning,
            })
    _bulk(session, GoogleHealthSession, gh_session_rows)
    total_rows += len(gh_summary_rows) + len(gh_session_rows)

    # --- Calendar (fictional connection + one calendar + accumulated events) ---
    session.add(IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]"))
    session.add(IntegrationConnection(provider="google_health", status="connected", scopes_json="[]"))
    calendar_id = _uuid()
    session.add(CalendarCalendar(id=calendar_id, external_calendar_id="primary", summary="Fictional Primary", access_role="owner", is_owned=True, timezone="Europe/London", selected=True))
    session.commit()
    CALENDAR_EVENTS = 6000
    cal_rows = []
    for i in range(CALENDAR_EVENTS):
        event_start = base_time + timedelta(days=int(DAYS * i / CALENDAR_EVENTS), hours=9)
        cal_rows.append({
            "id": _uuid(), "calendar_id": calendar_id, "external_event_id": f"event-{i}",
            "title": f"Fictional event #{i}", "description": None, "location": None, "all_day": False,
            "start_datetime": event_start, "end_datetime": event_start + timedelta(hours=1), "start_date": None, "end_date": None,
            "event_timezone": "Europe/London", "etag": None, "source_updated_at": event_start, "fetched_at": event_start,
        })
    _bulk(session, CalendarEventCache, cal_rows)
    total_rows += len(cal_rows)

    # --- Documents + chunks + FTS ---
    documents_dir = settings.data_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    DOCUMENTS = 80
    for i in range(DOCUMENTS):
        content = f"Fictional document #{i} content.\n" * 20
        sha = hashlib.sha256(content.encode()).hexdigest()
        (documents_dir / f"{sha}.txt").write_text(content)
        doc = Document(
            id=_uuid(), domain_id=domain_ids[i % len(domain_ids)], original_filename=f"fictional-doc-{i}.txt",
            stored_relative_path=f"documents/{sha}.txt", mime_type="text/plain", sha256=sha,
            size_bytes=len(content), status="ready",
        )
        session.add(doc)
        session.flush()
        for c in range(10):
            chunk = DocumentChunk(id=_uuid(), document_id=doc.id, chunk_index=c, content=f"Fictional chunk #{c} of document #{i}, realistic sentence length for search relevance testing.")
            session.add(chunk)
            session.flush()
            upsert_document_chunk_fts(session, chunk, doc.domain_id)
    session.commit()
    total_rows += DOCUMENTS * 11

    # --- Action proposals + audit events ---
    ACTIONS = 1400
    statuses = ["succeeded"] * 3 + ["denied", "failed", "expired"]
    action_rows, audit_rows = [], []
    for i in range(ACTIONS):
        proposal_id = _uuid()
        created = base_time + timedelta(days=int(DAYS * i / ACTIONS))
        action_rows.append({
            "id": proposal_id, "capability_id": "memory.create", "domain_id": domain_ids[i % len(domain_ids)],
            "permission_level": "confirm", "arguments_json": json.dumps({"scope": "domain", "kind": "fact", "title": f"T{i}", "content": "c"}),
            "reason": f"Fictional reason #{i}.", "expected_effect": f"Create a memory titled 'T{i}'.",
            "payload_digest": hashlib.sha256(f"digest-{i}".encode()).hexdigest(), "status": statuses[i % len(statuses)],
            "source": "manual_proposal", "confirmation_token": None, "confirmation_expires_at": None,
            "confirmation_used_at": None, "result_json": None, "error_summary": None,
            "created_at": created, "updated_at": created,
        })
        audit_rows.append({"id": _uuid(), "action_proposal_id": proposal_id, "event_type": "proposed", "detail": None, "created_at": created})
        audit_rows.append({"id": _uuid(), "action_proposal_id": proposal_id, "event_type": statuses[i % len(statuses)], "detail": None, "created_at": created})
    _bulk(session, ActionProposal, action_rows)
    _bulk(session, ActionAuditEvent, audit_rows)
    total_rows += len(action_rows) + len(audit_rows)

    # --- Skills (same mutual-FK ordering as memories/summaries above) ---
    skill_rows, skill_version_rows, skill_updates = [], [], []
    for i in range(15):
        skill_id, version_id = _uuid(), _uuid()
        skill_rows.append({"id": skill_id, "slug": f"fictional-skill-{i}", "name": f"Fictional skill {i}", "description": "A synthetic skill.", "domain_id": domain_ids[i % len(domain_ids)], "invocation_phrases_json": "[]", "status": "active" if i % 3 else "draft", "created_by": "user", "created_at": base_time, "updated_at": base_time, "current_version_id": None})
        skill_version_rows.append({"id": version_id, "skill_id": skill_id, "version_number": 1, "name": f"Fictional skill {i}", "description": "A synthetic skill.", "workflow_steps_json": json.dumps([{"capability_id": "memory.create", "description": "Log a fact"}]), "change_reason": None, "created_at": base_time})
        skill_updates.append({"skill_id": skill_id, "version_id": version_id})
    _bulk(session, Skill, skill_rows)
    _bulk(session, SkillVersion, skill_version_rows)
    session.execute(text("UPDATE skills SET current_version_id = :version_id WHERE id = :skill_id"), skill_updates)
    session.commit()
    total_rows += len(skill_rows) + len(skill_version_rows)

    # --- Routine runs (3 types, daily/weekly cadence, 5 years) ---
    routine_rows = []
    for routine_type, interval_days in (("morning_briefing", 1), ("evening_checkin", 1), ("weekly_review", 7)):
        n = DAYS // interval_days
        for i in range(n):
            started = base_time + timedelta(days=i * interval_days)
            routine_rows.append({
                "id": _uuid(), "routine_type": routine_type, "trigger": "scheduled", "started_at": started,
                "completed_at": started + timedelta(seconds=2), "outcome": "succeeded", "reason": None,
                "output_json": json.dumps({"sections": [{"title": "Today", "lines": [{"text": f"Fictional line {i}", "source_ref": f"record:{i:08x}"}]}]}),
                "responses_json": "{}", "selected_domains_json": "[]",
            })
    _bulk(session, RoutineRun, routine_rows)
    total_rows += len(routine_rows)

    # --- Integration sync history (bounded to 50/provider by the real app's
    # own trimming logic — generating more would be unrealistic, not just
    # unnecessary). ---
    sync_rows = []
    for provider in ("google_calendar", "google_health"):
        for i in range(50):
            started = base_time + timedelta(days=DAYS - 50 + i)
            sync_rows.append({
                "id": _uuid(), "provider": provider, "trigger": "scheduled", "started_at": started,
                "completed_at": started + timedelta(seconds=3), "outcome": "succeeded", "reason": None,
                "result_summary_json": json.dumps({"events": 5}),
            })
    _bulk(session, IntegrationSyncRun, sync_rows)
    total_rows += len(sync_rows)

    BENCHMARK_REPORT["generation_seconds"] = round(time.monotonic() - start, 2)
    BENCHMARK_REPORT["total_rows_generated"] = total_rows


def _db_size_mb(settings: Settings) -> float:
    return settings.database_path.stat().st_size / (1024 * 1024)


def test_report_multiyear_dataset_scale_and_database_size(
    multiyear_session: Session, multiyear_settings: Settings
) -> None:
    counts = {
        "conversations": multiyear_session.query(Conversation).count(),
        "messages": multiyear_session.query(Message).count(),
        "agent_runs": multiyear_session.query(AgentRun).count(),
        "context_snapshots": multiyear_session.query(ContextSnapshot).count(),
        "memory_items": multiyear_session.query(MemoryItem).count(),
        "memory_versions": multiyear_session.query(MemoryVersion).count(),
        "structured_records": multiyear_session.query(StructuredRecord).count(),
        "google_health_daily_summaries": multiyear_session.query(GoogleHealthDailySummary).count(),
        "google_health_sessions": multiyear_session.query(GoogleHealthSession).count(),
        "calendar_events": multiyear_session.query(CalendarEventCache).count(),
        "documents": multiyear_session.query(Document).count(),
        "document_chunks": multiyear_session.query(DocumentChunk).count(),
        "action_proposals": multiyear_session.query(ActionProposal).count(),
        "action_audit_events": multiyear_session.query(ActionAuditEvent).count(),
        "routine_runs": multiyear_session.query(RoutineRun).count(),
        "integration_sync_runs": multiyear_session.query(IntegrationSyncRun).count(),
        "domain_summary_versions": multiyear_session.query(DomainSummaryVersion).count(),
    }
    BENCHMARK_REPORT["row_counts"] = counts
    BENCHMARK_REPORT["sum_of_row_counts"] = sum(counts.values())
    BENCHMARK_REPORT["database_size_mb"] = round(_db_size_mb(multiyear_settings), 2)
    print("\n--- Multi-year (5y) scale benchmark dataset ---")
    print(json.dumps(BENCHMARK_REPORT, indent=2))
    assert BENCHMARK_REPORT["database_size_mb"] < MAX_DATABASE_SIZE_MB
    assert BENCHMARK_REPORT["generation_seconds"] < THRESHOLDS["dataset_generation"]


def test_cold_startup_at_multiyear_scale(multiyear_settings: Settings) -> None:
    from app.database import build_engine

    start = time.monotonic()
    engine = build_engine(multiyear_settings.database_url)
    session_factory = build_sessionmaker(engine)
    with session_factory() as session:
        domains = session.query(Domain).all()
    elapsed = time.monotonic() - start
    engine.dispose()
    BENCHMARK_REPORT["cold_startup_seconds"] = round(elapsed, 4)
    assert len(domains) == 6
    assert elapsed < THRESHOLDS["cold_startup"], f"cold startup took {elapsed:.2f}s (threshold {THRESHOLDS['cold_startup']}s)"


def test_fts_search_at_multiyear_scale(multiyear_session: Session) -> None:
    start = time.monotonic()
    results = fts_service.search_memory_fts(multiyear_session, "fictional memory", limit=20)
    elapsed = time.monotonic() - start
    BENCHMARK_REPORT["fts_search_seconds"] = round(elapsed, 4)
    assert len(results) > 0
    assert elapsed < THRESHOLDS["fts_search"], f"FTS search took {elapsed:.2f}s (threshold {THRESHOLDS['fts_search']}s)"


def test_context_construction_at_multiyear_scale(multiyear_session: Session) -> None:
    body = multiyear_session.query(Domain).filter_by(slug="body").one()
    conv = multiyear_session.query(Conversation).filter_by(domain_id=body.id).first()
    assert conv is not None

    start = time.monotonic()
    package = context_builder.build_context(
        multiyear_session, conversation=conv, domain=body, additional_domain_ids=[],
        query_text="fictional weight entries over five years", max_recent_messages=20,
    )
    elapsed = time.monotonic() - start
    BENCHMARK_REPORT["context_construction_seconds"] = round(elapsed, 4)
    assert len(package.system_prompt) > 0
    assert elapsed < THRESHOLDS["context_construction"], f"context construction took {elapsed:.2f}s (threshold {THRESHOLDS['context_construction']}s)"


def test_conversation_listing_and_loading_at_multiyear_scale(multiyear_session: Session) -> None:
    body = multiyear_session.query(Domain).filter_by(slug="body").one()

    start = time.monotonic()
    conversations = multiyear_session.execute(
        select(Conversation).where(Conversation.domain_id == body.id).order_by(Conversation.created_at.desc())
    ).scalars().all()
    list_elapsed = time.monotonic() - start

    start = time.monotonic()
    messages = multiyear_session.execute(
        select(Message).where(Message.conversation_id == conversations[0].id).order_by(Message.created_at)
    ).scalars().all()
    load_elapsed = time.monotonic() - start

    BENCHMARK_REPORT["conversation_list_seconds"] = round(list_elapsed, 4)
    BENCHMARK_REPORT["message_load_seconds"] = round(load_elapsed, 4)
    assert len(conversations) == 260
    assert len(messages) == 12
    assert list_elapsed < THRESHOLDS["conversation_list"]
    assert load_elapsed < THRESHOLDS["message_load"]


def test_integration_and_routine_history_reads_at_multiyear_scale(multiyear_session: Session) -> None:
    start = time.monotonic()
    sync_history = multiyear_session.execute(
        select(IntegrationSyncRun).where(IntegrationSyncRun.provider == "google_calendar").order_by(IntegrationSyncRun.started_at.desc())
    ).scalars().all()
    calendar_events = multiyear_session.execute(select(CalendarEventCache)).scalars().all()
    health_summaries = multiyear_session.execute(select(GoogleHealthDailySummary)).scalars().all()
    integration_elapsed = time.monotonic() - start

    start = time.monotonic()
    routine_history = multiyear_session.execute(
        select(RoutineRun).where(RoutineRun.routine_type == "morning_briefing").order_by(RoutineRun.started_at.desc()).limit(30)
    ).scalars().all()
    routine_elapsed = time.monotonic() - start

    BENCHMARK_REPORT["integration_history_read_seconds"] = round(integration_elapsed, 4)
    BENCHMARK_REPORT["routine_history_read_seconds"] = round(routine_elapsed, 4)
    assert len(sync_history) == 50
    assert len(calendar_events) == 6000
    assert len(health_summaries) == DAYS
    assert len(routine_history) == 30
    assert integration_elapsed < THRESHOLDS["integration_history_read"]
    assert routine_elapsed < THRESHOLDS["routine_history_read"]


def test_export_validate_restore_and_writability_at_multiyear_scale(
    multiyear_settings: Settings, multiyear_session: Session, tmp_path: Path
) -> None:
    multiyear_session.close()

    start = time.monotonic()
    export_result = export_service.create_export(multiyear_settings)
    export_elapsed = time.monotonic() - start
    archive_size_mb = export_result.path.stat().st_size / (1024 * 1024)

    start = time.monotonic()
    validation = import_service.validate_archive(export_result.path)
    validate_elapsed = time.monotonic() - start
    assert validation.ok, validation.errors

    restore_target = tmp_path / "restored"
    restore_target.mkdir()
    target_settings = Settings(jarvis_data_dir=str(restore_target))
    start = time.monotonic()
    restore_result = import_service.restore_archive(export_result.path, target_settings)
    restore_elapsed = time.monotonic() - start

    # Restored-database writability — a genuine post-restore write, not just
    # a read, using the restored database's own engine/session.
    from app.database import build_engine

    restored_engine = build_engine(target_settings.database_url)
    restored_session_factory = build_sessionmaker(restored_engine)
    write_start = time.monotonic()
    with restored_session_factory() as restored_session:
        body = restored_session.query(Domain).filter_by(slug="body").one()
        restored_session.add(Conversation(id=_uuid(), domain_id=body.id, title="Post-restore writability check"))
        restored_session.commit()
        written = restored_session.query(Conversation).filter_by(title="Post-restore writability check").one_or_none()
    write_elapsed = time.monotonic() - write_start
    restored_engine.dispose()

    BENCHMARK_REPORT["export_seconds"] = round(export_elapsed, 2)
    BENCHMARK_REPORT["archive_size_mb"] = round(archive_size_mb, 2)
    BENCHMARK_REPORT["validate_seconds"] = round(validate_elapsed, 2)
    BENCHMARK_REPORT["restore_seconds"] = round(restore_elapsed, 2)
    BENCHMARK_REPORT["post_restore_write_seconds"] = round(write_elapsed, 4)
    print("\n--- Multi-year export/restore/writability benchmark ---")
    print(json.dumps(BENCHMARK_REPORT, indent=2))

    assert restore_result.domains_restored == 6
    assert restore_result.conversations_restored == 260 * 6
    assert written is not None
    assert export_elapsed < THRESHOLDS["export"], f"export took {export_elapsed:.2f}s (threshold {THRESHOLDS['export']}s)"
    assert validate_elapsed < THRESHOLDS["validate"], f"validate took {validate_elapsed:.2f}s (threshold {THRESHOLDS['validate']}s)"
    assert restore_elapsed < THRESHOLDS["restore"], f"restore took {restore_elapsed:.2f}s (threshold {THRESHOLDS['restore']}s)"
