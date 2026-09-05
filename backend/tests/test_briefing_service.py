"""Phase 12A: the on-demand Home situational briefing's deterministic
assembler. Every test uses fictional fixtures seeded directly into the
isolated test database — no real Google/Keychain/Hermes/model contact,
matching app/briefing_service.py's own "no model call, ever" guarantee."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import briefing_service
from app.models import Domain
from app.models_actions import ActionProposal
from app.models_integrations import CalendarCalendar, CalendarEventCache, GoogleHealthDailySummary, IntegrationConnection
from app.models_memory import StructuredRecord
from app.models_routines import RoutineRun
from app.models_scheduler import IntegrationSyncSchedule


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _life_task(db_session: Session, title: str, due_date: str | None, created_at: datetime | None = None) -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "life"),
        record_type="life_task",
        occurred_at=created_at or datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": due_date}),
    )
    if created_at is not None:
        record.created_at = created_at
    db_session.add(record)
    db_session.commit()
    return record


def _path_deadline(db_session: Session, title: str, due_date: str | None) -> StructuredRecord:
    record = StructuredRecord(
        domain_id=_domain_id(db_session, "path"),
        record_type="path_deadline",
        occurred_at=datetime.now(timezone.utc),
        payload_json=json.dumps({"title": title, "due_date": due_date}),
    )
    db_session.add(record)
    db_session.commit()
    return record


# --- Empty state -----------------------------------------------------------


def test_empty_state_when_nothing_notable(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=True, include_mind=False, include_people=False, now=now
    )
    assert briefing.items == []


# --- Deterministic priority ordering ---------------------------------------


def test_now_items_rank_before_next_and_watch(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Overdue rent", "2026-08-20")  # NOW (overdue)
    _life_task(db_session, "Due soon errand", "2026-08-30")  # NEXT (due tomorrow)
    # WATCH: a pending action proposal
    db_session.add(
        ActionProposal(
            capability_id="memory.create",
            domain_id=None,
            permission_level="confirm",
            arguments_json="{}",
            reason="test",
            expected_effect="test",
            payload_digest="a" * 64,
            status="proposed",
        )
    )
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    categories = [item.category for item in briefing.items]
    assert categories == sorted(categories, key=lambda c: {"now": 0, "next": 1, "watch": 2}[c])
    assert categories[0] == "now"
    assert "watch" in categories


def test_more_overdue_task_ranks_before_less_overdue_task(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Barely overdue", "2026-08-28")
    _life_task(db_session, "Very overdue", "2026-08-10")

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    now_items = [i for i in briefing.items if i.category == "now"]
    assert [i.title for i in now_items] == ["Very overdue", "Barely overdue"]


def test_imminent_calendar_event_ranks_before_overdue_task_within_now(db_session: Session) -> None:
    """A documented, deliberate Jarvis judgment call (see
    briefing_service.py's _PRIORITY_OVERDUE_BASE comment): a meeting
    starting imminently is more time-critical than a task that has
    already been overdue for days, so it ranks first within NOW."""
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
    db_session.add(calendar)
    db_session.flush()
    db_session.add(
        CalendarEventCache(
            calendar_id=calendar.id, external_event_id="ev1", title="Standup", all_day=False,
            start_datetime=now + timedelta(minutes=10),
        )
    )
    _life_task(db_session, "Very overdue", "2026-08-10")
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    now_items = [i for i in briefing.items if i.category == "now"]
    assert now_items[0].title == "Standup"


# --- Stable tie-breaking / determinism --------------------------------------


def test_assembling_twice_with_same_state_is_identical(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    _life_task(db_session, "Overdue A", "2026-08-20")
    _path_deadline(db_session, "Overdue B", "2026-08-21")

    b1 = briefing_service.assemble_home_briefing(db_session, include_body=False, include_mind=False, include_people=False, now=now)
    b2 = briefing_service.assemble_home_briefing(db_session, include_body=False, include_mind=False, include_people=False, now=now)
    assert [i.id for i in b1.items] == [i.id for i in b2.items]


def test_dedupe_collapses_identical_items() -> None:
    item = briefing_service.BriefingItem(
        id="x", category="watch", tone="attention", priority=1, title="t", subtitle=None, domain_slug=None,
        source_type="integration_sync", source_ids=("google_calendar",), reason="r", source_timestamp=None,
        freshness="stale", classification="factual", link_target="integrations_centre", fingerprint="abc123",
    )
    result = briefing_service._dedupe([item, item])
    assert len(result) == 1


# --- Cap at 3-5 items --------------------------------------------------------


def test_home_briefing_capped_at_max_items(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    for i in range(10):
        _life_task(db_session, f"Overdue task {i}", "2026-08-20")

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    assert len(briefing.items) <= briefing_service.HOME_BRIEFING_MAX_ITEMS


# --- BODY inclusion, MIND/PEOPLE strict exclusion ---------------------------


def test_body_included_surfaces_stale_health_data(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        IntegrationConnection(provider="google_health", status="connected", connected_at=now - timedelta(days=10))
    )
    db_session.add(GoogleHealthDailySummary(date=date(2026, 8, 24), steps=8000))
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=True, include_mind=False, include_people=False, now=now
    )
    assert any(i.source_type == "google_health" for i in briefing.items)
    assert any(i.domain_slug == "body" for i in briefing.items)


def test_body_excluded_never_surfaces_health_data(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        IntegrationConnection(provider="google_health", status="connected", connected_at=now - timedelta(days=10))
    )
    db_session.add(GoogleHealthDailySummary(date=date(2026, 8, 24), steps=8000))
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    assert not any(i.source_type == "google_health" for i in briefing.items)


def test_mind_and_people_never_surface_regardless_of_flags(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, "mind"), record_type="mind_checkin", occurred_at=now,
            payload_json=json.dumps({"mood": "anxious", "note": "private"}),
        )
    )
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, "people"), record_type="people_interaction", occurred_at=now,
            payload_json=json.dumps({"person": "Alex", "note": "private conversation"}),
        )
    )
    db_session.commit()

    # Even with both flags set True, no MIND/PEOPLE source exists in this
    # module — a structural guarantee, not merely a flag check.
    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=True, include_people=True, now=now
    )
    all_text = json.dumps([i.title + (i.subtitle or "") for i in briefing.items])
    assert "anxious" not in all_text
    assert "Alex" not in all_text
    assert not any(i.domain_slug in ("mind", "people") for i in briefing.items)


# --- Strict domain boundaries ------------------------------------------------


def test_build_checkpoint_item_scoped_to_build_domain(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        StructuredRecord(
            domain_id=_domain_id(db_session, "build"), record_type="build_checkpoint", occurred_at=now,
            payload_json=json.dumps({"project": "Alpha", "summary": "Shipped tokenizer fix"}),
        )
    )
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    build_items = [i for i in briefing.items if i.source_type == "build_checkpoint"]
    assert len(build_items) == 1
    assert build_items[0].domain_slug == "build"
    assert build_items[0].link_target == "domain:build"


# --- Pending approval surfaced, never executed ------------------------------


def test_pending_action_proposal_surfaced_never_executed(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    proposal = ActionProposal(
        capability_id="memory.create", domain_id=None, permission_level="confirm", arguments_json="{}",
        reason="test", expected_effect="test", payload_digest="b" * 64, status="proposed",
    )
    db_session.add(proposal)
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    watch_items = [i for i in briefing.items if i.source_type == "action_proposal"]
    assert len(watch_items) == 1
    assert watch_items[0].link_target == "actions_centre"

    db_session.refresh(proposal)
    assert proposal.status == "proposed"  # never advanced by merely being surfaced


def test_failed_action_proposal_surfaced_as_failure_tone(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    proposal = ActionProposal(
        capability_id="memory.create", domain_id=None, permission_level="confirm", arguments_json="{}",
        reason="test", expected_effect="test", payload_digest="c" * 64, status="failed",
    )
    db_session.add(proposal)
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    failed = [i for i in briefing.items if i.id == "action_proposal:failed"]
    assert len(failed) == 1
    assert failed[0].tone == "failure"


# --- Failed / stale integration sync surfaced safely ------------------------


def test_failed_integration_sync_surfaced_without_secrets(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        IntegrationConnection(
            provider="google_calendar", status="connected", last_sync_status="failed",
            last_sync_at=now - timedelta(hours=1), last_error="rate_limited",
        )
    )
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    sync_items = [i for i in briefing.items if i.source_type == "integration_sync"]
    assert len(sync_items) == 1
    assert sync_items[0].tone == "failure"
    dumped = json.dumps([i.title + (i.subtitle or "") for i in sync_items])
    assert "access_token" not in dumped
    assert "refresh_token" not in dumped


def test_stale_scheduled_sync_surfaced_as_attention(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        IntegrationConnection(
            provider="google_calendar", status="connected", last_sync_status="ok",
            last_sync_at=now - timedelta(hours=10),
        )
    )
    schedule = db_session.get(IntegrationSyncSchedule, "google_calendar")
    schedule.enabled = True
    schedule.interval_minutes = 15
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    stale_items = [
        i for i in briefing.items if i.id == "integration_sync:google_calendar" and i.freshness == "stale"
    ]
    assert len(stale_items) == 1
    assert stale_items[0].tone == "attention"
    assert stale_items[0].freshness == "stale"


def test_not_connected_integration_never_surfaces(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=True, include_mind=False, include_people=False, now=now
    )
    assert not any(i.source_type == "integration_sync" for i in briefing.items)
    statuses = {s.source_type: s.status for s in briefing.sources}
    assert statuses["calendar"] == "not_connected"
    assert statuses["google_health"] == "not_connected"


# --- Failed routine run surfaced ---------------------------------------------


def test_recent_failed_routine_run_surfaced(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        RoutineRun(
            routine_type="morning_briefing", trigger="scheduled", started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=2), outcome="failed", reason="unexpected error: ValueError",
            selected_domains_json="[]",
        )
    )
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    routine_items = [i for i in briefing.items if i.source_type == "routine_run"]
    assert len(routine_items) == 1
    assert routine_items[0].tone == "failure"
    assert routine_items[0].link_target == "routine_centre"


def test_old_failed_routine_run_not_surfaced(db_session: Session) -> None:
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    db_session.add(
        RoutineRun(
            routine_type="morning_briefing", trigger="scheduled", started_at=now - timedelta(days=30),
            completed_at=now - timedelta(days=30), outcome="failed", reason="stale failure",
            selected_domains_json="[]",
        )
    )
    db_session.commit()

    briefing = briefing_service.assemble_home_briefing(
        db_session, include_body=False, include_mind=False, include_people=False, now=now
    )
    assert not any(i.source_type == "routine_run" for i in briefing.items)


# --- No model call ------------------------------------------------------------


def test_briefing_service_module_never_imports_a_model_provider() -> None:
    """Comments may mention Hermes/models to explain *why* this module
    never calls one; the actual guarantee checked here is that it imports
    no provider/agent module and calls no such function at all."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(briefing_service))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
    for forbidden_module in ("app.providers", "app.providers.base", "app.providers.hermes", "app.turn_service"):
        assert forbidden_module not in imported_names

    call_names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "send_turn" not in call_names


# --- Settings persistence ------------------------------------------------------


def test_settings_default_matches_recorded_privacy_selection(db_session: Session) -> None:
    settings = briefing_service.get_or_create_settings(db_session)
    assert settings.include_body is True
    assert settings.include_mind is False
    assert settings.include_people is False


def test_set_include_body_never_enables_mind_or_people(db_session: Session) -> None:
    settings = briefing_service.set_include_body(db_session, False)
    assert settings.include_body is False
    assert settings.include_mind is False
    assert settings.include_people is False
