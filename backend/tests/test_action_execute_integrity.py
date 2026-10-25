"""Regression tests for guarded-action execution integrity.

Covers the audit's confirmed defects: two concurrent executes of one
approval both succeeding (duplicate side effect), a local capability
committing its change before the action's own status (so crash recovery
claimed a completed change never happened), and an uncertain Google
Calendar create (timeout or 5xx after Google stored the event) being
recorded as a terminal failure that invited a duplicate.

State is checked independently: rows actually present in the database
and events actually held by the fake Google Calendar.
"""

from __future__ import annotations

import json
import threading

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import action_service
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.models_actions import ActionProposal
from app.models_memory import MemoryItem, MemoryVersion
from app.providers import google_calendar as gcal_provider
from tests.test_action_calendar_recovery import (
    FakeGoogleCalendar,
    _calendar,
    _client,
    _fresh_store,
    _grant_write_scope,
    _propose_and_approve_create,
)


def _memory_count(session: Session, title: str) -> int:
    return session.execute(
        select(func.count())
        .select_from(MemoryItem)
        .join(MemoryVersion, MemoryVersion.id == MemoryItem.current_version_id)
        .where(MemoryVersion.title == title)
    ).scalar_one()


def _approved_memory_proposal(session: Session, title: str):
    proposal = action_service.propose_action(
        session,
        capability_id="memory.create",
        domain_id=None,
        arguments={"scope": "global", "kind": "fact", "title": title, "content": "c"},
        reason="test",
    )
    return action_service.approve_action(session, proposal.id, payload_digest=proposal.payload_digest)


def test_concurrent_executes_of_one_approval_have_exactly_one_effect(memory_settings: Settings) -> None:
    engine = build_engine(memory_settings.database_url)
    factory = build_sessionmaker(engine)
    try:
        for trial in range(15):
            title = f"race-{trial}"
            with factory() as s:
                approved = _approved_memory_proposal(s, title)
                pid, token = approved.id, approved.confirmation_token

            barrier = threading.Barrier(2)
            outcomes: list[str] = []

            def run() -> None:
                with factory() as s:
                    barrier.wait()
                    try:
                        outcomes.append(action_service.execute_action(s, pid, confirmation_token=token).status)
                    except action_service.ActionError:
                        outcomes.append("refused")

            threads = [threading.Thread(target=run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            with factory() as s:
                assert _memory_count(s, title) == 1, (trial, outcomes)
                assert s.get(ActionProposal, pid).status == "succeeded"
            assert sorted(outcomes) == ["refused", "succeeded"], (trial, outcomes)
    finally:
        engine.dispose()


def test_replay_after_success_is_refused(db_session: Session) -> None:
    approved = _approved_memory_proposal(db_session, "once")
    action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)
    with pytest.raises(action_service.ActionError):
        action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)
    assert _memory_count(db_session, "once") == 1


def test_payload_changed_after_approval_is_refused(db_session: Session) -> None:
    approved = _approved_memory_proposal(db_session, "original")
    row = db_session.get(ActionProposal, approved.id)
    row.arguments_json = json.dumps(
        {"scope": "global", "kind": "fact", "title": "tampered", "content": "c"}, sort_keys=True
    )
    db_session.commit()

    with pytest.raises(action_service.ActionError, match="approved digest"):
        action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)
    assert _memory_count(db_session, "tampered") == 0
    assert _memory_count(db_session, "original") == 0
    assert db_session.get(ActionProposal, approved.id).status == "approved"


def test_expired_approval_is_refused(db_session: Session) -> None:
    from datetime import datetime, timedelta, timezone

    approved = _approved_memory_proposal(db_session, "late")
    row = db_session.get(ActionProposal, approved.id)
    row.confirmation_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(action_service.ActionError):
        action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)
    assert db_session.get(ActionProposal, approved.id).status == "expired"
    assert _memory_count(db_session, "late") == 0


@pytest.mark.parametrize(
    "capability_id,arguments,domain_slug",
    [
        ("memory.create", {"scope": "global", "kind": "fact", "title": "crash-mem", "content": "c"}, None),
        ("domain_summary.update", {"content": "crash summary"}, "build"),
        (
            "structured_record.create",
            {"record_type": "life_task", "payload": {"title": "crash task"}},
            "life",
        ),
    ],
)
def test_crash_before_final_commit_leaves_no_local_change(
    memory_settings: Settings, monkeypatch: pytest.MonkeyPatch, capability_id, arguments, domain_slug
) -> None:
    """Simulates the process dying after the capability ran but before the
    'succeeded' commit. Before the fix all three local capabilities had
    already committed their change by then, so recovery's 'did not happen'
    was false. Now the change must be absent, matching what recovery says."""
    from app.models import Domain
    from app.models_memory import DomainSummaryVersion, StructuredRecord

    engine = build_engine(memory_settings.database_url)
    factory = build_sessionmaker(engine)
    try:
        with factory() as s:
            domain_id = s.query(Domain).filter_by(slug=domain_slug).one().id if domain_slug else None
            proposal = action_service.propose_action(
                s, capability_id=capability_id, domain_id=domain_id, arguments=arguments, reason="test"
            )
            approved = action_service.approve_action(s, proposal.id, payload_digest=proposal.payload_digest)
            pid, token = approved.id, approved.confirmation_token

        class Crash(BaseException):
            pass

        real_record = action_service._record_event

        def crash_on_success(session, proposal, event_type, detail=None):
            if event_type == "succeeded":
                raise Crash()
            return real_record(session, proposal, event_type, detail)

        monkeypatch.setattr(action_service, "_record_event", crash_on_success)
        with factory() as s:
            with pytest.raises(Crash):
                action_service.execute_action(s, pid, confirmation_token=token)
        monkeypatch.setattr(action_service, "_record_event", real_record)

        with factory() as s:
            assert s.get(ActionProposal, pid).status == "executing"
            assert s.query(MemoryItem).count() == 0
            assert s.query(DomainSummaryVersion).count() == 0
            assert s.query(StructuredRecord).count() == 0
            assert action_service.expire_interrupted_executions(s) == 1
            recovered = s.get(ActionProposal, pid)
            assert recovered.status == "failed"
            assert "did not happen" in recovered.error_summary
    finally:
        engine.dispose()


def test_skill_created_record_is_searchable_in_recall(db_session: Session) -> None:
    from app.models import Domain
    from app.recall_service import search

    life = db_session.query(Domain).filter_by(slug="life").one()
    proposal = action_service.propose_action(
        db_session,
        capability_id="structured_record.create",
        domain_id=life.id,
        arguments={"record_type": "life_task", "payload": {"title": "renew zebra passport"}},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)
    results = search(db_session, query="zebra")
    assert any(r.source_type == "structured_record" for r in results.results)


# --- Calendar create with an uncertain outcome --------------------------


def _wrap(google: FakeGoogleCalendar, mode: str):
    """Lets the fake store the event, then loses or spoils the response."""

    def handler(request: httpx.Request) -> httpx.Response:
        is_insert = request.method == "POST" and request.url.path.endswith("/events")
        if is_insert and mode == "connect_error":
            raise httpx.ConnectError("no route to host", request=request)
        if is_insert and mode == "timeout_before_store":
            raise httpx.ReadTimeout("timed out before Google stored it", request=request)
        response = google.handler(request)
        if is_insert and response.status_code == 200:
            if mode == "read_timeout":
                raise httpx.ReadTimeout("response lost after Google stored the event", request=request)
            if mode == "503":
                return httpx.Response(503, json={"error": "backendError"})
        if mode == "lookup_down" and request.method == "GET":
            raise httpx.ConnectError("lookup failed", request=request)
        return response

    return handler


@pytest.mark.parametrize("mode", ["read_timeout", "503"])
def test_lost_response_after_google_stored_event_is_reconciled_as_success(db_session: Session, mode: str) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    google = FakeGoogleCalendar()
    approved = _propose_and_approve_create(db_session, calendar)

    result = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(_wrap(google, mode)),
        credential_store=_fresh_store(),
    )
    assert result.status == "succeeded", result.error_summary
    assert len(google.events) == 1
    assert json.loads(result.result_json)["external_event_id"] == gcal_provider.deterministic_event_id(approved.id)


@pytest.mark.parametrize("mode", ["timeout_before_store", "connect_error"])
def test_confirmed_absent_create_is_safely_retryable_without_duplicates(db_session: Session, mode: str) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    google = FakeGoogleCalendar()
    approved = _propose_and_approve_create(db_session, calendar)
    original_token = approved.confirmation_token

    first = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=original_token,
        http_client=_client(_wrap(google, mode)),
        credential_store=_fresh_store(),
    )
    assert first.status == "approved"
    assert "Safe to retry" in first.error_summary
    assert len(google.events) == 0
    assert first.confirmation_token != original_token

    second = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=first.confirmation_token,
        http_client=_client(google.handler),
        credential_store=_fresh_store(),
    )
    assert second.status == "succeeded"
    assert len(google.events) == 1


def test_uncertain_create_with_unreachable_lookup_needs_review(db_session: Session) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    google = FakeGoogleCalendar()
    approved = _propose_and_approve_create(db_session, calendar)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            google.handler(request)
            raise httpx.ReadTimeout("lost", request=request)
        raise httpx.ConnectError("lookup failed", request=request)

    result = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(handler),
        credential_store=_fresh_store(),
    )
    assert result.status == "needs_review"
    assert len(google.events) == 1


def test_definite_4xx_create_failure_is_still_failed(db_session: Session) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    result = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(handler),
        credential_store=_fresh_store(),
    )
    assert result.status == "failed"


def test_deleted_event_after_lost_response_is_needs_review_not_success(db_session: Session) -> None:
    """Google keeps a deleted event readable with status "cancelled"; that
    must never be taken as proof the create succeeded (review finding)."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    google = FakeGoogleCalendar()
    approved = _propose_and_approve_create(db_session, calendar)

    def handler(request: httpx.Request) -> httpx.Response:
        response = google.handler(request)
        if request.method == "POST" and response.status_code == 200:
            for event in google.events:
                event["status"] = "cancelled"  # deleted by the user before the check
            raise httpx.ReadTimeout("lost", request=request)
        return response

    result = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(handler),
        credential_store=_fresh_store(),
    )
    assert result.status == "needs_review"


def test_conflict_with_a_deleted_tagged_event_is_needs_review(db_session: Session) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    google = FakeGoogleCalendar()
    approved = _propose_and_approve_create(db_session, calendar)
    google.insert_with_id(event_id=gcal_provider.deterministic_event_id(approved.id), jarvis_action_id=approved.id)
    google.events[0]["status"] = "cancelled"

    result = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(google.handler),
        credential_store=_fresh_store(),
    )
    assert result.status == "needs_review"


def test_tick_scheduled_before_stop_does_nothing_after_stop(memory_settings: Settings) -> None:
    from app.credential_store import FakeCredentialStore
    from app.scheduler_runtime import SchedulerRuntime

    engine = build_engine(memory_settings.database_url)
    runtime = SchedulerRuntime(build_sessionmaker(engine), FakeCredentialStore(), None)
    ran = []
    runtime._run_tick_locked = lambda: ran.append("tick")
    try:
        runtime._stopping = True  # what stop() sets before waiting on the lock
        runtime._run_tick()
        assert ran == []
        runtime._stopping = False
        runtime._run_tick()
        assert ran == ["tick"]
    finally:
        engine.dispose()
