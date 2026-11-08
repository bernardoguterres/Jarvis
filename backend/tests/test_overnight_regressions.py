"""Overnight pass regression test suite.

Verifies fixes for:
1. Action proposal lazy expiration on single proposal fetch (`get_proposal_or_404`).
2. Action proposal recall sync on status transitions (succeeded, expired, approved, denied).
3. Calendar event cache date/time population, home briefing inclusion, and recall indexing on guarded actions.
4. Decision Room reopen resets chosen option to active, allowing editing and clean re-decision.
5. FTS5 query sanitizer with null bytes and hostile syntax.
6. Import archive validation cleanup on extraction failure.
"""

from __future__ import annotations

import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import action_service, calendar_capability, decision_service, fts_service, import_service, recall_service
from app.briefing_service import todays_calendar_events
from app.models import Domain
from app.models_decisions import DecisionCriterion, DecisionOption
from app.models_integrations import CalendarCalendar, CalendarEventCache
from app.recall_service import search


def test_action_proposal_lazy_expiration_on_single_fetch(db_session: Session) -> None:
    proposal = action_service.propose_action(
        db_session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": "T1", "content": "c1"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    assert approved.status == "approved"

    # Fast-forward past confirmation TTL
    approved.confirmation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)
    db_session.flush()
    db_session.commit()

    # get_proposal_or_404 must detect expiration lazily
    fetched = action_service.get_proposal_or_404(db_session, proposal.id)
    assert fetched.status == "expired"


def test_action_proposal_recall_sync_on_succeeded_and_expiration(db_session: Session) -> None:
    proposal = action_service.propose_action(
        db_session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": "CanaryAlpha", "content": "c1"},
        reason="Create CanaryAlpha proposal",
    )
    db_session.commit()

    # Verify action proposal is indexed in recall_fts
    rows = db_session.execute(
        text("SELECT title, content FROM recall_fts WHERE source_type = 'action_proposal' AND source_id = :id"),
        {"id": proposal.id},
    ).fetchall()
    assert len(rows) == 1
    assert "CanaryAlpha" in rows[0][1]

    # Approve and execute
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    executed = action_service.execute_action(
        db_session, proposal.id, confirmation_token=approved.confirmation_token
    )
    assert executed.status == "succeeded"

    # Verify recall_fts reflects the proposal after execution
    rows_after = db_session.execute(
        text("SELECT title, content FROM recall_fts WHERE source_type = 'action_proposal' AND source_id = :id"),
        {"id": proposal.id},
    ).fetchall()
    assert len(rows_after) == 1


def test_calendar_capability_caches_dates_times_and_syncs_recall(db_session: Session) -> None:
    import json
    from app.models_integrations import IntegrationConnection

    conn = db_session.get(IntegrationConnection, "google_calendar")
    if conn is None:
        conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]")
        db_session.add(conn)
    conn.status = "connected"
    conn.scopes_json = json.dumps([
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        calendar_capability.WRITE_SCOPE,
    ])

    calendar = CalendarCalendar(
        external_calendar_id="primary",
        summary="Main",
        access_role="owner",
        is_owned=True,
        selected=True,
    )
    db_session.add(calendar)
    db_session.flush()

    today_date = date(2026, 11, 8)

    # 1. Timed event
    timed_args = {
        "calendar_id": calendar.id,
        "title": "Strategy Sync Overnight",
        "description": "Discussing roadmap",
        "location": "Boardroom",
        "all_day": False,
        "start": "2026-11-08T10:00:00Z",
        "end": "2026-11-08T11:00:00Z",
        "timezone": "UTC",
    }
    calendar_capability._cache_created_event(db_session, calendar, "ext_event_1", timed_args)
    db_session.commit()

    cached = db_session.query(CalendarEventCache).filter_by(external_event_id="ext_event_1").first()
    assert cached is not None
    assert cached.start_datetime is not None
    assert cached.start_datetime.hour == 10
    assert cached.event_timezone == "UTC"

    # Verify todays_calendar_events includes this event!
    events_today = todays_calendar_events(db_session, today_date)
    assert any(ev.external_event_id == "ext_event_1" for ev in events_today)

    # Verify recall indexing
    recall_res = search(db_session, "Strategy Sync Overnight")
    assert any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_res.results)

    # 2. Update event title
    fake_client = MagicMock()
    from app.credential_store import FakeCredentialStore
    fake_store = FakeCredentialStore()
    fake_store.set("google_calendar", "access_token", "fake-token")
    fake_store.set("google_calendar", "refresh_token", "fake-refresh")
    fake_store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    from unittest.mock import patch
    with patch("app.providers.google_calendar.update_event") as mock_update:
        calendar_capability.execute_event_update(
            db_session,
            domain_id=None,
            arguments={"calendar_id": calendar.id, "event_id": cached.id, "title": "Updated Strategy Meeting"},
            http_client=fake_client,
            credential_store=fake_store,
        )
    db_session.commit()

    # Verify updated title in recall
    recall_updated = search(db_session, "Updated Strategy Meeting")
    assert any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_updated.results)

    # 3. Delete event
    with patch("app.providers.google_calendar.delete_event") as mock_delete:
        calendar_capability.execute_event_delete(
            db_session,
            domain_id=None,
            arguments={"calendar_id": calendar.id, "event_id": cached.id},
            http_client=fake_client,
            credential_store=fake_store,
        )
    db_session.commit()

    # Verify event is removed from recall
    recall_deleted = search(db_session, "Updated Strategy Meeting")
    assert not any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_deleted.results)


def test_decision_reopen_resets_chosen_options_and_enables_edit(db_session: Session) -> None:
    domain = db_session.query(Domain).filter_by(slug="life").first()
    assert domain is not None

    decision = decision_service.create_decision(
        db_session,
        title="Choose housing strategy",
        domain_slug="life",
    )
    opt1 = decision_service.add_option(db_session, decision.id, name="Rent apartment")
    opt2 = decision_service.add_option(db_session, decision.id, name="Buy house")
    crit = decision_service.add_criterion(db_session, decision.id, name="Flexibility", weight=4)

    decision_service.set_assessment(db_session, decision.id, option_id=opt1.id, criterion_id=crit.id, score=5)
    decision_service.set_assessment(db_session, decision.id, option_id=opt2.id, criterion_id=crit.id, score=2)

    # Decide on option 1
    decided = decision_service.decide(
        db_session,
        decision.id,
        selected_option_id=opt1.id,
        rationale="More flexible",
        decision_confidence=4,
    )
    assert decided.status == "decided"
    db_session.refresh(opt1)
    assert opt1.status == "chosen"

    # Editing an option should fail while decided
    with pytest.raises(decision_service.DecisionError, match="reopen it first"):
        decision_service.update_option(db_session, decision.id, opt1.id, name="Rent studio")

    # Reopen decision
    reopened = decision_service.reopen(db_session, decision.id)
    assert reopened.status == "reopened"
    db_session.refresh(opt1)
    db_session.refresh(opt2)

    # Option 1 must have been reset to active
    assert opt1.status == "active"
    assert opt2.status == "active"

    # Editing option 1 must now succeed!
    updated_opt1 = decision_service.update_option(db_session, decision.id, opt1.id, name="Rent luxury apartment")
    assert updated_opt1.name == "Rent luxury apartment"

    # Re-decide on option 2
    redecided = decision_service.decide(
        db_session,
        decision.id,
        selected_option_id=opt2.id,
        rationale="Changed priority to stability",
        decision_confidence=5,
    )
    assert redecided.status == "decided"
    db_session.refresh(opt1)
    db_session.refresh(opt2)
    assert opt2.status == "chosen"
    assert opt1.status == "active"


def test_fts_sanitizer_and_recall_search_handles_null_bytes_and_hostile_syntax(db_session: Session) -> None:
    hostile_queries = [
        "test\x00hostile null byte",
        "AND OR NOT NEAR/3 () \"\"\" : * ^",
        "unbalanced ( quotes \" and * prefix",
        "null\x00\x00everywhere\x01\x1f",
    ]

    for q in hostile_queries:
        safe = fts_service.sanitize_fts_query(q)
        assert "\x00" not in safe
        # Calling search must not raise any SQLite OperationalError
        res = search(db_session, q)
        assert isinstance(res.results, list)


def test_import_validate_cleans_up_tempdir_on_extraction_failure(tmp_path: Path) -> None:
    # Create a dummy zip file
    zip_file = tmp_path / "corrupt_test.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("manifest.json", "{}")

    temp_dir_before = set(Path(tempfile.gettempdir()).glob("jarvis-import-*"))

    from unittest.mock import patch
    with patch("app.import_service._extract_safely", side_effect=RuntimeError("Extraction failed")):
        with pytest.raises(RuntimeError, match="Extraction failed"):
            import_service.validate_archive(zip_file)

    temp_dir_after = set(Path(tempfile.gettempdir()).glob("jarvis-import-*"))
    leaked = temp_dir_after - temp_dir_before
    assert len(leaked) == 0, f"Leaked directories: {leaked}"


def test_proposal_expiration_at_get_and_execute_endpoints_with_zero_provider_calls(
    client, db_session: Session
) -> None:
    import json
    from unittest.mock import patch
    from app.models_integrations import CalendarCalendar, IntegrationConnection
    from app.recall_service import resolve_source_snapshot

    conn = db_session.get(IntegrationConnection, "google_calendar")
    if conn is None:
        conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]")
        db_session.add(conn)
    conn.status = "connected"
    conn.scopes_json = json.dumps([
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        calendar_capability.WRITE_SCOPE,
    ])

    calendar = CalendarCalendar(
        external_calendar_id="primary_exp",
        summary="Test Calendar",
        access_role="owner",
        is_owned=True,
        selected=True,
    )
    db_session.add(calendar)
    db_session.flush()
    db_session.commit()

    life_domain = db_session.query(Domain).filter_by(slug="life").first()
    assert life_domain is not None

    # 1. Propose an action
    resp = client.post(
        "/api/actions",
        json={
            "capability_id": "google_calendar.event.create",
            "domain_id": life_domain.id,
            "arguments": {
                "calendar_id": calendar.id,
                "title": "Expired Proposal Event",
                "all_day": False,
                "start": "2026-11-08T14:00:00Z",
                "end": "2026-11-08T15:00:00Z",
                "timezone": "UTC",
            },
            "reason": "Test proposal expiration",
        },
    )
    assert resp.status_code == 201
    prop_data = resp.json()
    proposal_id = prop_data["id"]
    assert prop_data["status"] == "proposed"

    # 2. Approve the proposal
    approve_resp = client.post(
        f"/api/actions/{proposal_id}/approve",
        json={"payload_digest": prop_data["payload_digest"]},
    )
    assert approve_resp.status_code == 200
    approved_data = approve_resp.json()
    assert approved_data["status"] == "approved"
    token = approved_data["confirmation_token"]
    assert token is not None

    # 3. Advance time beyond its TTL (confirmation_expires_at is now in the past)
    row = db_session.get(action_service.ActionProposal, proposal_id)
    row.confirmation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=15)
    db_session.commit()

    # 4. Check GET endpoint: detects expiration lazily
    get_resp = client.get(f"/api/actions/{proposal_id}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["proposal"]["status"] == "expired"

    # 5. Check execute endpoint with original token
    with patch("app.providers.google_calendar.create_event") as mock_create_event:
        exec_resp = client.post(
            f"/api/actions/{proposal_id}/execute",
            json={"confirmation_token": token},
        )
        # Execute endpoint must reject the request
        assert exec_resp.status_code == 403
        assert "expired" in exec_resp.json()["detail"].lower()
        # Assert action provider receives ZERO calls
        assert mock_create_event.call_count == 0

    # 6. Assert proposal state in DB is expired
    db_session.refresh(row)
    assert row.status == "expired"

    # 7. Assert Recall and proposal state agree
    snapshot = resolve_source_snapshot(db_session, "action_proposal", proposal_id)
    assert snapshot is not None
    assert "expired" in snapshot["content"]

    recall_results = search(db_session, "Expired Proposal Event")
    assert any(
        r.source_type == "action_proposal" and r.source_id == proposal_id for r in recall_results.results
    )


def test_calendar_mock_provider_create_update_delete_consistency_with_home_briefing_and_recall(
    db_session: Session,
) -> None:
    import json
    from unittest.mock import patch
    from app.credential_store import FakeCredentialStore
    from app.models_integrations import CalendarCalendar, CalendarEventCache, IntegrationConnection

    # Ensure integration connection and calendar exist
    conn = db_session.get(IntegrationConnection, "google_calendar")
    if conn is None:
        conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]")
        db_session.add(conn)
    conn.status = "connected"
    conn.scopes_json = json.dumps([
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
        calendar_capability.WRITE_SCOPE,
    ])

    calendar = CalendarCalendar(
        external_calendar_id="primary",
        summary="Main Calendar",
        access_role="owner",
        is_owned=True,
        selected=True,
    )
    db_session.add(calendar)
    db_session.flush()

    today_date = date(2026, 11, 8)
    store = FakeCredentialStore()
    store.set("google_calendar", "access_token", "fake-token")
    store.set("google_calendar", "refresh_token", "fake-refresh")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    fake_client = MagicMock()
    life_domain = db_session.query(Domain).filter_by(slug="life").first()
    assert life_domain is not None

    # --- 1. CREATE ---
    prop_create = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life_domain.id,
        arguments={
            "calendar_id": calendar.id,
            "title": "Quarterly Strategy Review",
            "description": "Executive review session",
            "location": "Room 401",
            "all_day": False,
            "start": "2026-11-08T09:00:00Z",
            "end": "2026-11-08T10:00:00Z",
            "timezone": "UTC",
        },
        reason="Schedule quarterly review",
    )
    approved_create = action_service.approve_action(db_session, prop_create.id, payload_digest=prop_create.payload_digest)

    with patch("app.providers.google_calendar.create_event", return_value="gcal_ext_123") as mock_create:
        executed_create = action_service.execute_action(
            db_session,
            prop_create.id,
            confirmation_token=approved_create.confirmation_token,
            http_client=fake_client,
            credential_store=store,
        )
        assert executed_create.status == "succeeded"
        assert mock_create.call_count == 1

    # Verify event cache exists
    cached = db_session.query(CalendarEventCache).filter_by(external_event_id="gcal_ext_123").first()
    assert cached is not None
    assert cached.title == "Quarterly Strategy Review"

    # Verify Home briefing includes the event
    briefing_events = todays_calendar_events(db_session, today_date)
    assert any(ev.id == cached.id and ev.title == "Quarterly Strategy Review" for ev in briefing_events)

    # Verify Recall search finds the event
    recall_hits = search(db_session, "Quarterly Strategy Review")
    assert any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_hits.results)

    # --- 2. UPDATE ---
    prop_update = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.update",
        domain_id=life_domain.id,
        arguments={
            "calendar_id": calendar.id,
            "event_id": cached.id,
            "title": "Updated Strategy & Roadmap",
            "description": "Updated agenda",
        },
        reason="Update strategy meeting agenda and title",
    )
    approved_update = action_service.approve_action(db_session, prop_update.id, payload_digest=prop_update.payload_digest)

    with patch("app.providers.google_calendar.update_event") as mock_update:
        executed_update = action_service.execute_action(
            db_session,
            prop_update.id,
            confirmation_token=approved_update.confirmation_token,
            http_client=fake_client,
            credential_store=store,
        )
        assert executed_update.status == "succeeded"
        assert mock_update.call_count == 1

    # Verify Home briefing reflects the updated title
    briefing_events_after_update = todays_calendar_events(db_session, today_date)
    assert any(ev.id == cached.id and ev.title == "Updated Strategy & Roadmap" for ev in briefing_events_after_update)
    assert not any(ev.id == cached.id and ev.title == "Quarterly Strategy Review" for ev in briefing_events_after_update)

    # Verify Recall search finds the updated title and no longer matches old title specific terms
    recall_updated_hits = search(db_session, "Roadmap")
    assert any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_updated_hits.results)
    recall_old_hits = search(db_session, "Quarterly")
    assert not any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_old_hits.results)

    # --- 3. DELETE ---
    prop_delete = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.delete",
        domain_id=life_domain.id,
        arguments={
            "calendar_id": calendar.id,
            "event_id": cached.id,
        },
        reason="Cancel strategy meeting",
    )
    approved_delete = action_service.approve_action(db_session, prop_delete.id, payload_digest=prop_delete.payload_digest)

    with patch("app.providers.google_calendar.delete_event") as mock_delete:
        executed_delete = action_service.execute_action(
            db_session,
            prop_delete.id,
            confirmation_token=approved_delete.confirmation_token,
            http_client=fake_client,
            credential_store=store,
        )
        assert executed_delete.status == "succeeded"
        assert mock_delete.call_count == 1

    # Verify Home briefing no longer contains the event
    briefing_events_after_delete = todays_calendar_events(db_session, today_date)
    assert not any(ev.id == cached.id for ev in briefing_events_after_delete)

    # Verify Recall no longer contains the event
    recall_deleted_hits = search(db_session, "Roadmap")
    assert not any(r.source_type == "calendar_event" and r.source_id == cached.id for r in recall_deleted_hits.results)
