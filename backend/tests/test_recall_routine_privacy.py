"""Routine runs are indexed in Recall as global (no owning domain), so
global results reach default Recall, Recall opened from any domain, and
Research/Decision evidence search. BODY/MIND/PEOPLE sections that
Bernardo opted into a routine must never reach that index, while the
LIFE/PATH/BUILD and Calendar sections stay searchable and the full output
stays in the Routine Centre. Also covers the `source_types=None` vs `[]`
contract. Fictional fixtures only, no Google/Keychain/Hermes/model call."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import decision_service, recall_index_service, recall_service, research_service, routine_service
from app.models import Domain
from app.models_integrations import CalendarCalendar, CalendarEventCache, GoogleHealthDailySummary
from app.models_memory import StructuredRecord
from app.models_routines import RoutineRun

T0 = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 27)

# Unique markers, one per sensitive source, so a hit can only come from
# that exact piece of content.
MIND_MARKER = "zebrafinchmind"
PEOPLE_MARKER = "zebrafinchpeople"
BODY_RECORD_MARKER = "zebrafinchbody"
BODY_STEPS = 7654321  # Google Health only carries numbers

LIFE_MARKER = "quokkalife"
PATH_MARKER = "quokkapath"
BUILD_MARKER = "quokkabuild"
CALENDAR_MARKER = "quokkacalendar"

SENSITIVE_QUERIES = (MIND_MARKER, PEOPLE_MARKER, BODY_RECORD_MARKER, str(BODY_STEPS))
PERMITTED_QUERIES = (LIFE_MARKER, PATH_MARKER, BUILD_MARKER, CALENDAR_MARKER)


def _clock():
    return T0


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _record(db_session: Session, slug: str, record_type: str, payload: dict) -> None:
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, slug), record_type=record_type, occurred_at=T0,
            payload_json=json.dumps(payload),
        )
    )


def _seed_everything(db_session: Session) -> None:
    _record(db_session, "mind", "mind_checkin", {"title": MIND_MARKER, "mood": MIND_MARKER})
    _record(db_session, "people", "people_interaction", {"title": PEOPLE_MARKER, "person": "Alex", "note": PEOPLE_MARKER})
    _record(db_session, "body", "body_symptom", {"title": BODY_RECORD_MARKER})
    db_session.add(GoogleHealthDailySummary(date=TODAY, steps=BODY_STEPS))
    _record(db_session, "life", "life_task", {"title": LIFE_MARKER})
    _record(db_session, "path", "path_deadline", {"title": PATH_MARKER})
    _record(db_session, "build", "build_checkpoint", {"project": "Jarvis", "summary": BUILD_MARKER})
    calendar = CalendarCalendar(
        external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True
    )
    db_session.add(calendar)
    db_session.flush()
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev1", title=CALENDAR_MARKER, all_day=False,
            start_datetime=datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc),
        )
    )
    db_session.commit()


def _run(db_session: Session, routine_type: str, selected_domains: list[str]) -> RoutineRun:
    routine_service.set_schedule(
        db_session, routine_type, enabled=False, local_time="09:00", timezone_name="UTC",
        weekday=6 if routine_type == "weekly_review" else None, selected_domains=selected_domains, clock=_clock,
    )
    run = routine_service.run_routine(db_session, routine_type, "manual", _clock)
    db_session.commit()
    assert run.outcome == "succeeded"
    return run


def _routine_hits(db_session: Session, query: str, **kwargs) -> list[recall_service.RecallResult]:
    result = recall_service.search(db_session, query, now=T0, **kwargs)
    return [r for r in result.results if r.source_type == "routine_run"]


def _indexed_routine_text(db_session: Session, run_id: str) -> str:
    row = db_session.execute(
        text("SELECT title || ' ' || content FROM recall_fts WHERE source_type = 'routine_run' AND source_id = :i"),
        {"i": run_id},
    ).first()
    assert row is not None
    return row[0]


ALL_SIX = ["body", "mind", "people", "life", "path", "build"]


@pytest.mark.parametrize("routine_type", ["morning_briefing", "weekly_review"])
def test_sensitive_routine_sections_never_reach_recall(db_session: Session, routine_type: str) -> None:
    _seed_everything(db_session)
    run = _run(db_session, routine_type, ALL_SIX)

    # Sanity: the sensitive content really is in this run's output.
    output = run.output_json or ""
    assert MIND_MARKER in output
    assert PEOPLE_MARKER in output
    assert str(BODY_STEPS) in output

    indexed = _indexed_routine_text(db_session, run.id)
    for query in SENSITIVE_QUERIES:
        assert query not in indexed
        # Default Recall (LIFE/PATH/BUILD + global).
        assert _routine_hits(db_session, query) == []
        # Recall opened from inside BUILD with global results enabled.
        assert _routine_hits(db_session, query, domain_slugs=["build"], include_global=True, current_domain="build") == []
        # Even a caller that names every domain cannot reach it through the
        # routine run (the real source records are a separate matter).
        assert _routine_hits(db_session, query, domain_slugs=ALL_SIX) == []


def test_permitted_routine_sections_remain_searchable(db_session: Session) -> None:
    _seed_everything(db_session)
    briefing = _run(db_session, "morning_briefing", ALL_SIX)
    review = _run(db_session, "weekly_review", ["life", "path", "build"])

    for query in PERMITTED_QUERIES:
        ids = {r.source_id for r in _routine_hits(db_session, query)}
        assert briefing.id in ids, query
    for query in (LIFE_MARKER, PATH_MARKER, BUILD_MARKER):
        ids = {r.source_id for r in _routine_hits(db_session, query)}
        assert review.id in ids, query


def test_full_sensitive_output_still_shown_in_routine_centre(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/mind/records",
        json={"record_type": "mind_checkin", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"mood": MIND_MARKER}},
    )
    assert resp.status_code == 201, resp.text
    resp = client.put(
        "/api/routines/morning_briefing/schedule",
        json={"enabled": False, "local_time": "08:00", "timezone": "UTC", "selected_domains": ["mind"]},
    )
    assert resp.status_code == 200, resp.text
    resp = client.post("/api/routines/morning_briefing/run")
    assert resp.status_code == 200, resp.text

    history = client.get("/api/routines/morning_briefing/history").json()
    texts = [line["text"] for s in history[0]["sections"] for line in s["lines"]]
    assert any(MIND_MARKER in t for t in texts)

    resp = client.get("/api/recall/search", params={"q": MIND_MARKER})
    assert [r for r in resp.json()["results"] if r["source_type"] == "routine_run"] == []


def test_research_evidence_cannot_retrieve_or_cite_sensitive_sections(db_session: Session) -> None:
    _seed_everything(db_session)
    run = _run(db_session, "weekly_review", ALL_SIX)
    workspace = research_service.create_workspace(db_session, title="Build plan")

    for query in SENSITIVE_QUERIES:
        hits = research_service.search_workspace_evidence(db_session, workspace.id, query)
        assert [r for r in hits.results if r.source_type == "routine_run"] == []

    # Adding the run directly (it is global, so the policy allows it) must
    # freeze only the sanitized text into the citation snapshot and brief.
    evidence = research_service.add_evidence(db_session, workspace.id, source_type="routine_run", source_id=run.id)
    brief = research_service.generate_deterministic_brief(db_session, workspace.id)
    frozen = " ".join([evidence.title_snapshot, evidence.snippet_snapshot or "", json.dumps(brief.__dict__, default=str)])
    for query in SENSITIVE_QUERIES:
        assert query not in frozen


def test_decision_evidence_cannot_retrieve_or_cite_sensitive_sections(db_session: Session) -> None:
    _seed_everything(db_session)
    run = _run(db_session, "morning_briefing", ALL_SIX)
    decision = decision_service.create_decision(db_session, title="Which project next")

    for query in SENSITIVE_QUERIES:
        hits = decision_service.search_decision_evidence(db_session, decision.id, query)
        assert [r for r in hits.results if r.source_type == "routine_run"] == []

    link = decision_service.add_evidence(db_session, decision.id, source_type="routine_run", source_id=run.id)
    brief = decision_service.generate_deterministic_brief(db_session, decision.id)
    frozen = " ".join([link.title_snapshot, link.snippet_snapshot or "", json.dumps(brief.__dict__, default=str)])
    for query in SENSITIVE_QUERIES:
        assert query not in frozen


def test_untagged_legacy_sections_fail_closed(db_session: Session) -> None:
    """A run written before sections carried a domain tag (or any section
    whose tag is missing/unknown) contributes no section text at all."""
    legacy = RoutineRun(
        routine_type="weekly_review", trigger="manual", started_at=T0, completed_at=T0, outcome="succeeded",
        selected_domains_json='["mind", "life"]',
        output_json=json.dumps(
            {
                "sections": [
                    {"title": "MIND — weekly review", "lines": [{"text": MIND_MARKER, "source_ref": None}]},
                    {"title": "LIFE — weekly review", "lines": [{"text": LIFE_MARKER, "source_ref": None}]},
                    {"title": "x", "domain_slug": "unknown", "lines": [{"text": PEOPLE_MARKER, "source_ref": None}]},
                ]
            }
        ),
    )
    db_session.add(legacy)
    db_session.commit()
    recall_index_service.sync_recall(db_session, "routine_run", legacy.id)
    db_session.commit()

    indexed = _indexed_routine_text(db_session, legacy.id)
    for marker in (MIND_MARKER, LIFE_MARKER, PEOPLE_MARKER):
        assert marker not in indexed


# --- already-indexed rows ---------------------------------------------------------


def _alembic_config(database_url: str):
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migration_purges_previously_indexed_sensitive_routine_text(data_dir: Path) -> None:
    """An installation indexed by the old renderer has MIND text sitting in
    `recall_fts`. Migration 0020 empties the derived index, the existing
    startup backfill rebuilds it with the current renderer, and the
    original routine output is left untouched."""
    from alembic import command

    from app.config import Settings
    from app.database import build_engine, build_sessionmaker
    from app.seed import seed_domains

    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()
    command.upgrade(_alembic_config(settings.database_url), "0019")

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
        _record(session, "mind", "mind_checkin", {"title": MIND_MARKER, "mood": MIND_MARKER})
        session.commit()
        run = _run(session, "weekly_review", ["mind", "life"])
        run_id = run.id
        original_output = run.output_json
        # Simulate the row the pre-fix renderer wrote: every section's text.
        session.execute(
            text("UPDATE recall_fts SET content = :c WHERE source_type = 'routine_run' AND source_id = :i"),
            {"c": f"MIND — weekly review {MIND_MARKER}", "i": run_id},
        )
        session.commit()
        assert [r.source_id for r in _routine_hits(session, MIND_MARKER)] == [run_id]
    engine.dispose()

    command.upgrade(_alembic_config(settings.database_url), "head")

    engine = build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        assert session.execute(text("SELECT COUNT(*) FROM recall_fts")).scalar_one() == 0
        # The same rebuild the startup backfill runs on an empty index.
        recall_index_service.rebuild_recall_index(session)
        assert _routine_hits(session, MIND_MARKER) == []
        assert MIND_MARKER not in _indexed_routine_text(session, run_id)
        assert session.get(RoutineRun, run_id).output_json == original_output
    engine.dispose()


def test_startup_backfill_reindexes_after_migration(client: TestClient) -> None:
    """End to end through the real app: after the index is emptied (what
    0020 does), the next startup's backfill repopulates it."""
    from app.main import create_app

    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": LIFE_MARKER}},
    )
    assert resp.status_code == 201
    client.put(
        "/api/routines/morning_briefing/schedule",
        json={"enabled": False, "local_time": "08:00", "timezone": "UTC", "selected_domains": []},
    )
    assert client.post("/api/routines/morning_briefing/run").status_code == 200

    from app.config import get_settings
    from app.database import build_engine, build_sessionmaker

    engine = build_engine(get_settings().database_url)
    with build_sessionmaker(engine)() as session:
        session.execute(text("DELETE FROM recall_fts"))
        session.commit()
    engine.dispose()

    with TestClient(create_app()) as restarted:
        results = restarted.get("/api/recall/search", params={"q": LIFE_MARKER}).json()["results"]
        assert {r["source_type"] for r in results} >= {"structured_record", "routine_run"}


# --- source_types: None vs [] vs explicit ----------------------------------------


def test_source_types_none_empty_and_explicit_are_distinct(db_session: Session) -> None:
    _seed_everything(db_session)
    _run(db_session, "morning_briefing", [])
    for record in db_session.query(StructuredRecord).all():
        recall_index_service.sync_recall(db_session, "structured_record", record.id)
    db_session.commit()

    default = {r.source_type for r in recall_service.search(db_session, LIFE_MARKER, now=T0).results}
    assert default == {"structured_record", "routine_run"}

    assert recall_service.search(db_session, LIFE_MARKER, source_types=[], now=T0).results == []

    explicit = {
        r.source_type for r in recall_service.search(db_session, LIFE_MARKER, source_types=["routine_run"], now=T0).results
    }
    assert explicit == {"routine_run"}

    # Unknown types are dropped; if nothing valid is left it matches nothing.
    assert recall_service.search(db_session, LIFE_MARKER, source_types=["not_a_type"], now=T0).results == []


def test_source_types_api_boundary(client: TestClient) -> None:
    resp = client.post(
        "/api/domains/life/records",
        json={"record_type": "life_task", "occurred_at": "2026-08-20T09:00:00Z", "payload": {"title": LIFE_MARKER}},
    )
    assert resp.status_code == 201

    omitted = client.get("/api/recall/search", params={"q": LIFE_MARKER}).json()["results"]
    assert len(omitted) == 1

    empty = client.get("/api/recall/search", params={"q": LIFE_MARKER, "source_types": ""}).json()
    assert empty["results"] == []
    assert empty["total_considered"] == 0

    explicit = client.get("/api/recall/search", params={"q": LIFE_MARKER, "source_types": "structured_record"}).json()
    assert [r["source_type"] for r in explicit["results"]] == ["structured_record"]

    other = client.get("/api/recall/search", params={"q": LIFE_MARKER, "source_types": "routine_run"}).json()
    assert other["results"] == []

    # Research and Decision evidence routes parse the parameter the same way.
    ws = client.post("/api/research/workspaces", json={"title": "ws"})
    assert ws.status_code in (200, 201), ws.text
    ws_id = ws.json()["id"]
    path = f"/api/research/workspaces/{ws_id}/evidence/search"
    assert len(client.get(path, params={"q": LIFE_MARKER}).json()["results"]) == 1
    assert client.get(path, params={"q": LIFE_MARKER, "source_types": ""}).json()["results"] == []

    dec = client.post("/api/decisions", json={"title": "d"})
    assert dec.status_code in (200, 201), dec.text
    dec_id = dec.json()["id"]
    path = f"/api/decisions/{dec_id}/evidence/search"
    assert len(client.get(path, params={"q": LIFE_MARKER}).json()["results"]) == 1
    assert client.get(path, params={"q": LIFE_MARKER, "source_types": ""}).json()["results"] == []
