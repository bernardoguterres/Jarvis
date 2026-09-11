"""Failure-injection tests for crash-safe recovery of interrupted Google
Calendar writes (hardening pass). execute_action's crash window sits
between marking a proposal 'executing' and its final succeeded/failed
commit; a Calendar write's real effect can outlive that window (it lives
in Google, not in Jarvis's own transaction), so an interrupted one must
never be reported as a definite failure and a recovered retry must never
create a duplicate event.

A tiny stateful fake stands in for Google Calendar itself (the create/
list/get endpoints actually used), never a real network call.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app import action_service
from app.calendar_capability import WRITE_SCOPE
from app.credential_store import FakeCredentialStore
from app.models import Domain
from app.models_integrations import CalendarCalendar, CalendarEventCache, IntegrationConnection


class FakeGoogleCalendar:
    """Minimal stateful fake for the three Calendar endpoints recovery
    depends on: create (POST events), search-by-private-property and
    single-event lookup (both GET events/...)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._next_id = 1

    def insert_directly(self, *, jarvis_action_id: str) -> str:
        """Simulates Google having already accepted a create whose HTTP
        response never made it back to Jarvis (the exact 'external
        success, lost response' crash window)."""
        external_id = f"ext-{self._next_id}"
        self._next_id += 1
        self.events.append(
            {"id": external_id, "extendedProperties": {"private": {"jarvis_action_id": jarvis_action_id}}}
        )
        return external_id

    def insert_with_id(self, *, event_id: str, jarvis_action_id: str | None) -> str:
        """Simulates Google already holding an event at a specific
        (deterministic) ID — used to model 'the earlier create actually
        landed on Google, tagged with this exact ID, before the crash/lost
        response'. `jarvis_action_id=None` models a same-ID collision with
        an event that carries no (or different) Jarvis metadata."""
        props = {"private": {"jarvis_action_id": jarvis_action_id}} if jarvis_action_id else {}
        self.events.append({"id": event_id, "extendedProperties": props})
        return event_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/events"):
            body = json.loads(request.content or b"{}")
            requested_id = body.get("id")
            if requested_id and any(e["id"] == requested_id for e in self.events):
                # Real Google behaviour: inserting with a caller-supplied
                # `id` that already exists on the calendar returns 409.
                return httpx.Response(409, json={"error": {"code": 409, "message": "Already Exists"}})
            external_id = requested_id or f"ext-{self._next_id}"
            if not requested_id:
                self._next_id += 1
            self.events.append({"id": external_id, **body})
            return httpx.Response(200, json={"id": external_id})
        if request.method == "GET" and path.endswith("/events"):
            prop = request.url.params.get("privateExtendedProperty")
            if prop:
                key, _, value = prop.partition("=")
                matches = [
                    e for e in self.events if e.get("extendedProperties", {}).get("private", {}).get(key) == value
                ]
                return httpx.Response(200, json={"items": [{"id": e["id"]} for e in matches]})
            return httpx.Response(200, json={"items": [{"id": e["id"]} for e in self.events]})
        if request.method == "GET" and "/events/" in path:
            event_id = path.rsplit("/", 1)[-1]
            for event in self.events:
                if event["id"] == event_id:
                    return httpx.Response(200, json=event)
            return httpx.Response(404, json={"error": "not_found"})
        return httpx.Response(404, json={"error": "unhandled"})


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _calendar(db_session: Session) -> CalendarCalendar:
    calendar = CalendarCalendar(
        external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True
    )
    db_session.add(calendar)
    db_session.commit()
    db_session.refresh(calendar)
    return calendar


def _grant_write_scope(db_session: Session) -> None:
    db_session.add(
        IntegrationConnection(provider="google_calendar", status="connected", scopes_json=json.dumps([WRITE_SCOPE]))
    )
    db_session.commit()


def _fresh_store() -> FakeCredentialStore:
    store = FakeCredentialStore()
    store.set("google_calendar", "client_id", "cid")
    store.set("google_calendar", "client_secret", "csecret")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    return store


def _life_id(db_session: Session) -> str:
    return db_session.query(Domain).filter_by(slug="life").one().id


def _propose_and_approve_create(db_session: Session, calendar: CalendarCalendar):
    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=_life_id(db_session),
        arguments={
            "calendar_id": calendar.id,
            "title": "Recovery test event",
            "all_day": True,
            "start": "2026-09-01",
            "end": "2026-09-02",
        },
        reason="test",
    )
    return action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)


def _force_executing(db_session: Session, proposal) -> None:
    """Simulates exactly the state execute_action leaves behind if the
    process is killed after the 'executing' commit but before the final
    succeeded/failed commit — never actually crashing a process."""
    stuck = action_service.get_proposal_or_404(db_session, proposal.id)
    stuck.status = "executing"
    stuck.confirmation_used_at = datetime.now(timezone.utc)
    db_session.commit()


def test_failure_before_external_request_marks_failed_not_stuck(db_session: Session) -> None:
    """No credential store contents at all means ensure_fresh_access_token
    raises before any HTTP request reaches Google — nothing external ever
    happened, so a definite 'failed' (not 'needs_review') is the honest
    outcome, and the proposal must not be left stuck in 'executing'."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    executed = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(lambda r: httpx.Response(500)),
        credential_store=FakeCredentialStore(),  # empty: no access/refresh token
    )
    assert executed.status == "failed"
    assert executed.error_summary


def test_recovery_confirms_succeeded_when_google_already_has_the_tagged_event(db_session: Session) -> None:
    """Covers both 'external success followed by a lost response' and
    'interruption after external success but before local success
    persistence': from recovery's point of view these are the same
    observable state — a stuck 'executing' proposal whose tagged event
    already exists on Google. Recovery must resolve it to a confirmed
    'succeeded', never a guess."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    external_id = fake_google.insert_directly(jarvis_action_id=approved.id)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(fake_google.handler), credential_store=_fresh_store()
    )
    assert recovered_count == 1

    recovered = action_service.get_proposal_or_404(db_session, approved.id)
    assert recovered.status == "succeeded"
    assert json.loads(recovered.result_json)["external_event_id"] == external_id
    cache_row = (
        db_session.query(CalendarEventCache)
        .filter_by(calendar_id=calendar.id, external_event_id=external_id)
        .one_or_none()
    )
    assert cache_row is not None
    event_types = [e.event_type for e in recovered.audit_events]
    assert event_types[-1] == "succeeded"

    # A second startup sweep is a no-op: never re-flag an already-resolved
    # proposal or duplicate its audit trail.
    assert action_service.expire_interrupted_executions(db_session, http_client=None, credential_store=None) == 0


def test_recovery_confirms_absence_and_retry_creates_exactly_one_event(db_session: Session) -> None:
    """'Restart reconciliation confirming absence' + 'repeated retry not
    creating a duplicate event': when Google confirms no tagged event
    exists, recovery must make the proposal safely retryable (never
    'succeeded', never a permanent 'failed'), and retrying it for real
    must result in exactly one event on the fake calendar."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)
    original_token = approved.confirmation_token
    _force_executing(db_session, approved)

    fake_google = FakeGoogleCalendar()
    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(fake_google.handler), credential_store=_fresh_store()
    )
    assert recovered_count == 1

    retryable = action_service.get_proposal_or_404(db_session, approved.id)
    assert retryable.status == "approved"
    assert retryable.confirmation_token is not None
    # A fresh single-use token — never the one already consumed by the
    # interrupted attempt (that one must not become replayable).
    assert retryable.confirmation_token != original_token

    executed = action_service.execute_action(
        db_session,
        retryable.id,
        confirmation_token=retryable.confirmation_token,
        http_client=_client(fake_google.handler),
        credential_store=_fresh_store(),
    )
    assert executed.status == "succeeded"
    assert len(fake_google.events) == 1

    # Recovery running again afterward (e.g. another restart) must not
    # touch a now-settled proposal, and must not create a second event.
    assert action_service.expire_interrupted_executions(db_session, http_client=None, credential_store=None) == 0
    assert len(fake_google.events) == 1


def test_recovery_marks_needs_review_when_lookup_unavailable(db_session: Session) -> None:
    """'External lookup temporarily unavailable': Google cannot be reached
    to confirm or deny the outcome, so the proposal must land in
    'needs_review' — never 'succeeded' (unconfirmed) and never 'failed'
    (the effect may well have happened)."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)
    _force_executing(db_session, approved)

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unreachable", request=request)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(unavailable), credential_store=_fresh_store()
    )
    assert recovered_count == 1

    reviewed = action_service.get_proposal_or_404(db_session, approved.id)
    assert reviewed.status == "needs_review"
    assert reviewed.error_summary
    assert "verify" in reviewed.error_summary.lower() or "confirm" in reviewed.error_summary.lower()

    # needs_review is genuinely terminal until a human resolves it — no
    # path re-executes it, and it is not silently re-swept into anything
    # else on a later restart.
    with pytest.raises(action_service.ActionError):
        action_service.execute_action(db_session, approved.id, confirmation_token=approved.confirmation_token)


def test_recovery_without_http_client_marks_calendar_actions_needs_review(db_session: Session) -> None:
    """If recovery itself has no way to reach Google (e.g. the integration
    HTTP client failed to construct at startup), a stuck Calendar action
    must land in 'needs_review', never a fabricated 'failed'."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(db_session, http_client=None, credential_store=None)
    assert recovered_count == 1
    assert action_service.get_proposal_or_404(db_session, approved.id).status == "needs_review"


def test_delete_recovery_confirms_succeeded_when_event_already_gone(db_session: Session) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    cached = CalendarEventCache(calendar_id=calendar.id, external_event_id="ext-1", title="To delete", all_day=True)
    db_session.add(cached)
    db_session.commit()
    db_session.refresh(cached)

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.delete",
        domain_id=_life_id(db_session),
        arguments={"calendar_id": calendar.id, "event_id": cached.id},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(lambda r: httpx.Response(404, json={})), credential_store=_fresh_store()
    )
    assert recovered_count == 1
    resolved = action_service.get_proposal_or_404(db_session, approved.id)
    assert resolved.status == "succeeded"
    assert db_session.get(CalendarEventCache, cached.id) is None


def test_delete_recovery_confirms_still_present_and_is_safely_retryable(db_session: Session) -> None:
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    cached = CalendarEventCache(calendar_id=calendar.id, external_event_id="ext-1", title="To delete", all_day=True)
    db_session.add(cached)
    db_session.commit()
    db_session.refresh(cached)

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.delete",
        domain_id=_life_id(db_session),
        arguments={"calendar_id": calendar.id, "event_id": cached.id},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session,
        http_client=_client(lambda r: httpx.Response(200, json={"id": "ext-1"})),
        credential_store=_fresh_store(),
    )
    assert recovered_count == 1
    retryable = action_service.get_proposal_or_404(db_session, approved.id)
    assert retryable.status == "approved"
    assert db_session.get(CalendarEventCache, cached.id) is not None


def test_expire_if_needed_never_touches_an_executing_proposal(db_session: Session) -> None:
    """Objective 3: an executing action must not be incorrectly expired by
    the ordinary time-based lazy-expiry path while reconciliation is what
    it actually needs — expiry only ever resolves a stale 'approved'."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)
    stuck = action_service.get_proposal_or_404(db_session, approved.id)
    stuck.status = "executing"
    stuck.confirmation_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)  # long past window
    db_session.commit()

    proposals = action_service.list_proposals(db_session, status=None)
    still_executing = next(p for p in proposals if p.id == approved.id)
    assert still_executing.status == "executing"


# --- Deterministic Google event-ID hardening (verification pass) ---------
#
# Google Calendar's own documented mechanism for preventing a duplicate
# create after a successful write whose response was lost is a
# caller-supplied, valid event ID (not merely private-property search
# after the fact). The tests below cover the deterministic-ID scheme
# itself and its interaction with the reconciliation logic above.


def test_same_action_id_always_derives_the_same_event_id() -> None:
    from app.providers import google_calendar as gcal_provider

    action_id = "11111111-1111-1111-1111-111111111111"
    assert gcal_provider.deterministic_event_id(action_id) == gcal_provider.deterministic_event_id(action_id)


def test_different_action_ids_derive_different_event_ids() -> None:
    from app.providers import google_calendar as gcal_provider

    a = gcal_provider.deterministic_event_id("11111111-1111-1111-1111-111111111111")
    b = gcal_provider.deterministic_event_id("22222222-2222-2222-2222-222222222222")
    assert a != b


def test_deterministic_event_id_satisfies_google_charset_and_length() -> None:
    import re

    from app.providers import google_calendar as gcal_provider

    event_id = gcal_provider.deterministic_event_id("33333333-3333-3333-3333-333333333333")
    # Google: lowercase base32hex alphabet (a-v, 0-9), length 5-1024.
    assert re.fullmatch(r"[0-9a-v]{5,1024}", event_id)


def test_create_sends_deterministic_id_and_lost_response_retry_gets_conflict_not_a_duplicate(
    db_session: Session,
) -> None:
    """Models 'external success followed by a lost response' directly at
    the provider level: the first create call actually reaches Google
    (event is inserted under the deterministic ID) but the response never
    reaches the client, so the caller sees a transport error. Retrying the
    exact same create (same idempotency_key) must hit Google's 409 rather
    than silently creating a second event."""
    from app.providers import google_calendar as gcal_provider

    fake_google = FakeGoogleCalendar()
    action_id = "44444444-4444-4444-4444-444444444444"
    expected_id = gcal_provider.deterministic_event_id(action_id)

    def lossy_first_response(request: httpx.Request) -> httpx.Response:
        fake_google.handler(request)  # Google actually processes the insert...
        raise httpx.ReadError("connection reset before response", request=request)  # ...but it never arrives.

    with pytest.raises(httpx.ReadError):
        gcal_provider.create_event(
            client=_client(lossy_first_response),
            access_token="AT1",
            calendar_id="primary",
            title="Lost response event",
            description=None,
            location=None,
            all_day=True,
            start="2026-09-01",
            end="2026-09-02",
            timezone_name=None,
            idempotency_key=action_id,
        )
    assert len(fake_google.events) == 1
    assert fake_google.events[0]["id"] == expected_id

    # Retry: same action, same derived ID — Google now reports conflict.
    with pytest.raises(gcal_provider.GoogleCalendarConflictError) as excinfo:
        gcal_provider.create_event(
            client=_client(fake_google.handler),
            access_token="AT1",
            calendar_id="primary",
            title="Lost response event",
            description=None,
            location=None,
            all_day=True,
            start="2026-09-01",
            end="2026-09-02",
            timezone_name=None,
            idempotency_key=action_id,
        )
    assert excinfo.value.event_id == expected_id
    # Still exactly one event on the fake calendar — no duplicate.
    assert len(fake_google.events) == 1


def test_execute_confirms_conflicting_event_as_success_when_metadata_matches(db_session: Session) -> None:
    """The capability layer (not just the provider) must treat a 409 whose
    existing event carries this action's own jarvis_action_id as a
    confirmed success, not a failure — 'recovery fetching and confirming
    the existing event', exercised through a live execute_action call."""
    from app.providers import google_calendar as gcal_provider

    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    expected_id = gcal_provider.deterministic_event_id(approved.id)
    # Google already holds the event at this action's deterministic ID,
    # correctly tagged — as if an earlier attempt's response was lost.
    fake_google.insert_with_id(event_id=expected_id, jarvis_action_id=approved.id)

    executed = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(fake_google.handler),
        credential_store=_fresh_store(),
    )
    assert executed.status == "succeeded"
    assert json.loads(executed.result_json)["external_event_id"] == expected_id
    # No second event was created — the conflict was reconciled, not retried.
    assert len(fake_google.events) == 1


def test_execute_marks_needs_review_when_conflicting_event_metadata_mismatches(db_session: Session) -> None:
    """A same-ID collision with an event that does NOT carry this action's
    own metadata must never be treated as success — the honest outcome is
    needs_review, not a guess in either direction."""
    from app.providers import google_calendar as gcal_provider

    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    expected_id = gcal_provider.deterministic_event_id(approved.id)
    # Some other event occupies this exact ID, tagged with a different
    # action's ID entirely (or none) — must never be confused for this
    # action's own write.
    fake_google.insert_with_id(event_id=expected_id, jarvis_action_id="some-other-action-id")

    executed = action_service.execute_action(
        db_session,
        approved.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(fake_google.handler),
        credential_store=_fresh_store(),
    )
    assert executed.status == "needs_review"
    assert executed.error_summary
    assert "verify" in executed.error_summary.lower() or "confirm" in executed.error_summary.lower()


def test_recovery_confirms_succeeded_via_deterministic_id_directly(db_session: Session) -> None:
    """The deterministic-ID lookup path itself (not the private-property
    fallback): recovery must find and confirm the event by directly
    fetching this action's own deterministic event ID."""
    from app.providers import google_calendar as gcal_provider

    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    expected_id = gcal_provider.deterministic_event_id(approved.id)
    fake_google.insert_with_id(event_id=expected_id, jarvis_action_id=approved.id)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(fake_google.handler), credential_store=_fresh_store()
    )
    assert recovered_count == 1
    recovered = action_service.get_proposal_or_404(db_session, approved.id)
    assert recovered.status == "succeeded"
    assert json.loads(recovered.result_json)["external_event_id"] == expected_id


def test_recovery_marks_needs_review_on_deterministic_id_metadata_mismatch(db_session: Session) -> None:
    """Recovery must apply the same never-guess rule as live execution: an
    event at this action's deterministic ID with mismatching metadata is
    needs_review, never a false 'succeeded'."""
    from app.providers import google_calendar as gcal_provider

    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    expected_id = gcal_provider.deterministic_event_id(approved.id)
    fake_google.insert_with_id(event_id=expected_id, jarvis_action_id="some-other-action-id")
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(fake_google.handler), credential_store=_fresh_store()
    )
    assert recovered_count == 1
    reviewed = action_service.get_proposal_or_404(db_session, approved.id)
    assert reviewed.status == "needs_review"


def test_recovery_falls_back_to_legacy_private_property_lookup(db_session: Session) -> None:
    """An event created before the deterministic-ID scheme existed carries
    only the private-property tag, at an arbitrary (non-deterministic) ID —
    recovery must still find and confirm it via the legacy search path
    once the direct deterministic-ID lookup comes back empty."""
    calendar = _calendar(db_session)
    _grant_write_scope(db_session)
    approved = _propose_and_approve_create(db_session, calendar)

    fake_google = FakeGoogleCalendar()
    legacy_external_id = fake_google.insert_directly(jarvis_action_id=approved.id)
    _force_executing(db_session, approved)

    recovered_count = action_service.expire_interrupted_executions(
        db_session, http_client=_client(fake_google.handler), credential_store=_fresh_store()
    )
    assert recovered_count == 1
    recovered = action_service.get_proposal_or_404(db_session, approved.id)
    assert recovered.status == "succeeded"
    assert json.loads(recovered.result_json)["external_event_id"] == legacy_external_id
