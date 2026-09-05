"""Google Calendar write capabilities go through the exact same Phase 8
action lifecycle — exact-payload approval, replay/tamper rejection — with
all HTTP mocked."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

import json

from app import action_service
from app.calendar_capability import WRITE_SCOPE
from app.capabilities import CapabilityError
from app.credential_store import FakeCredentialStore
from app.models import Domain
from app.models_integrations import CalendarCalendar, IntegrationConnection


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _owned_selected_calendar(db_session: Session) -> CalendarCalendar:
    calendar = CalendarCalendar(
        external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True
    )
    db_session.add(calendar)
    db_session.commit()
    db_session.refresh(calendar)
    return calendar


def _grant_write_scope(db_session: Session) -> None:
    """Simulates a Calendar connection where Google actually granted the
    write scope (i.e. Bernardo completed the incremental-consent round trip
    for calendar.events.owned) — never assumed, always read from what the
    connection row actually records."""
    conn = db_session.get(IntegrationConnection, "google_calendar")
    if conn is None:
        conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]")
        db_session.add(conn)
    conn.status = "connected"
    conn.scopes_json = json.dumps(
        [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.readonly",
            WRITE_SCOPE,
        ]
    )
    db_session.commit()


def _read_only_connection(db_session: Session) -> None:
    """Simulates a Calendar connection authorized for read-only access
    only — the write scope was never requested/granted."""
    conn = db_session.get(IntegrationConnection, "google_calendar")
    if conn is None:
        conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="[]")
        db_session.add(conn)
    conn.status = "connected"
    conn.scopes_json = json.dumps(
        [
            "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
            "https://www.googleapis.com/auth/calendar.events.readonly",
        ]
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


def test_event_create_requires_timezone_for_timed_event(db_session: Session) -> None:
    calendar = _owned_selected_calendar(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    with pytest.raises(CapabilityError):
        action_service.propose_action(
            db_session,
            capability_id="google_calendar.event.create",
            domain_id=life.id,
            arguments={
                "calendar_id": calendar.id,
                "title": "Test event",
                "all_day": False,
                "start": "2026-09-01T10:00:00",
                "end": "2026-09-01T11:00:00",
            },
            reason="test",
        )


def test_event_create_all_day_does_not_require_timezone(db_session: Session) -> None:
    calendar = _owned_selected_calendar(db_session)
    _grant_write_scope(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life.id,
        arguments={
            "calendar_id": calendar.id,
            "title": "All day test",
            "all_day": True,
            "start": "2026-09-01",
            "end": "2026-09-02",
        },
        reason="test",
    )
    assert proposal.status == "proposed"
    assert "all-day" in proposal.expected_effect


def test_event_create_full_lifecycle_exact_payload_approval(db_session: Session) -> None:
    calendar = _owned_selected_calendar(db_session)
    _grant_write_scope(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    store = _fresh_store()

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life.id,
        arguments={
            "calendar_id": calendar.id,
            "title": "Jarvis test event",
            "all_day": False,
            "start": "2026-09-01T10:00:00",
            "end": "2026-09-01T11:00:00",
            "timezone": "Europe/London",
        },
        reason="live acceptance test event",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "created-ext-id"})

    executed = action_service.execute_action(
        db_session, proposal.id, confirmation_token=approved.confirmation_token, http_client=_client(handler), credential_store=store
    )
    assert executed.status == "succeeded"
    import json

    assert json.loads(executed.result_json)["external_event_id"] == "created-ext-id"


def test_write_rejected_for_unselected_calendar(db_session: Session) -> None:
    calendar = CalendarCalendar(external_calendar_id="x", summary="Not selected", access_role="owner", is_owned=True, selected=False)
    db_session.add(calendar)
    db_session.commit()
    db_session.refresh(calendar)
    _grant_write_scope(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    store = _fresh_store()

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life.id,
        arguments={"calendar_id": calendar.id, "title": "T", "all_day": True, "start": "2026-09-01", "end": "2026-09-02"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    executed = action_service.execute_action(
        db_session, proposal.id, confirmation_token=approved.confirmation_token, http_client=_client(lambda r: httpx.Response(200)), credential_store=store
    )
    assert executed.status == "failed"
    assert "not selected" in (executed.error_summary or "")


def test_write_rejected_for_non_owned_calendar(db_session: Session) -> None:
    calendar = CalendarCalendar(external_calendar_id="x", summary="Shared", access_role="reader", is_owned=False, selected=True)
    db_session.add(calendar)
    db_session.commit()
    db_session.refresh(calendar)
    _grant_write_scope(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    store = _fresh_store()

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life.id,
        arguments={"calendar_id": calendar.id, "title": "T", "all_day": True, "start": "2026-09-01", "end": "2026-09-02"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    executed = action_service.execute_action(
        db_session, proposal.id, confirmation_token=approved.confirmation_token, http_client=_client(lambda r: httpx.Response(200)), credential_store=store
    )
    assert executed.status == "failed"
    assert "own" in (executed.error_summary or "")


def test_event_delete_full_lifecycle(db_session: Session) -> None:
    from app.models_integrations import CalendarEventCache

    calendar = _owned_selected_calendar(db_session)
    _grant_write_scope(db_session)
    event = CalendarEventCache(calendar_id=calendar.id, external_event_id="ext-1", title="To delete", all_day=True)
    db_session.add(event)
    db_session.commit()
    db_session.refresh(event)
    life = db_session.query(Domain).filter_by(slug="life").one()
    store = _fresh_store()

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.delete",
        domain_id=life.id,
        arguments={"calendar_id": calendar.id, "event_id": event.id},
        reason="cleanup test event",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)
    executed = action_service.execute_action(
        db_session,
        proposal.id,
        confirmation_token=approved.confirmation_token,
        http_client=_client(lambda r: httpx.Response(204)),
        credential_store=store,
    )
    assert executed.status == "succeeded"
    assert db_session.get(CalendarEventCache, event.id) is None


def test_read_only_authorization_cannot_propose_calendar_mutation(db_session: Session) -> None:
    """A connection authorized for read-only scopes only (no incremental
    consent for calendar.events.owned performed yet) must never be able to
    even propose a write — the scope check happens at propose time, before
    any approval/execution round trip. Never assume a requested scope was
    granted."""
    calendar = _owned_selected_calendar(db_session)
    _read_only_connection(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()

    with pytest.raises(CapabilityError, match="calendar.events.owned"):
        action_service.propose_action(
            db_session,
            capability_id="google_calendar.event.create",
            domain_id=life.id,
            arguments={"calendar_id": calendar.id, "title": "T", "all_day": True, "start": "2026-09-01", "end": "2026-09-02"},
            reason="test",
        )


def test_read_only_authorization_cannot_execute_calendar_mutation(db_session: Session) -> None:
    """Defense in depth: even if a proposal somehow exists (e.g. it was
    proposed while write scope was granted, then Bernardo revoked/narrowed
    consent before executing), execute-time must re-check and refuse."""
    calendar = _owned_selected_calendar(db_session)
    _grant_write_scope(db_session)
    life = db_session.query(Domain).filter_by(slug="life").one()
    store = _fresh_store()

    proposal = action_service.propose_action(
        db_session,
        capability_id="google_calendar.event.create",
        domain_id=life.id,
        arguments={"calendar_id": calendar.id, "title": "T", "all_day": True, "start": "2026-09-01", "end": "2026-09-02"},
        reason="test",
    )
    approved = action_service.approve_action(db_session, proposal.id, payload_digest=proposal.payload_digest)

    # Scope narrowed to read-only between approval and execution.
    _read_only_connection(db_session)

    executed = action_service.execute_action(
        db_session, proposal.id, confirmation_token=approved.confirmation_token, http_client=_client(lambda r: httpx.Response(200)), credential_store=store
    )
    assert executed.status == "failed"
    assert "calendar.events.owned" in (executed.error_summary or "")


def test_missing_scopes_json_handled_safely(db_session: Session) -> None:
    """A connection with no scopes recorded at all (corrupt/absent
    scopes_json) must be treated as ungranted, never as granted."""
    calendar = _owned_selected_calendar(db_session)
    conn = IntegrationConnection(provider="google_calendar", status="connected", scopes_json="not-json")
    db_session.add(conn)
    db_session.commit()
    life = db_session.query(Domain).filter_by(slug="life").one()

    with pytest.raises(CapabilityError):
        action_service.propose_action(
            db_session,
            capability_id="google_calendar.event.create",
            domain_id=life.id,
            arguments={"calendar_id": calendar.id, "title": "T", "all_day": True, "start": "2026-09-01", "end": "2026-09-02"},
            reason="test",
        )


def test_incremental_consent_preserves_previously_granted_read_scopes(db_session: Session) -> None:
    """Simulates Google's include_granted_scopes=true response after
    incremental consent: the returned `scope` string is the union of
    previously-granted read scopes plus the newly-granted write scope, not
    just the newly requested one. integration_service must store exactly
    what Google returns, not what was merely requested."""
    from datetime import datetime, timezone

    from app import integration_service
    from app.credential_store import FakeCredentialStore
    from app.oauth_flow import OAuthFlowStore

    store = FakeCredentialStore()
    integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
    flow_store = OAuthFlowStore()
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=True
    )
    state = httpx.QueryParams(httpx.URL(result.authorization_url).query.decode())["state"]
    assert "include_granted_scopes=true" in result.authorization_url

    union_scope = (
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly "
        "https://www.googleapis.com/auth/calendar.events.readonly "
        "https://www.googleapis.com/auth/calendar.events.owned"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": union_scope})

    conn = integration_service.handle_google_calendar_callback(
        db_session, store=store, flow_store=flow_store, http_client=_client(handler), code="authcode", state=state
    )
    granted = json.loads(conn.scopes_json)
    assert "https://www.googleapis.com/auth/calendar.calendarlist.readonly" in granted
    assert "https://www.googleapis.com/auth/calendar.events.readonly" in granted
    assert "https://www.googleapis.com/auth/calendar.events.owned" in granted


def test_client_type_and_redirect_uri_match_web_application_flow() -> None:
    """The documented setup (README.md) says 'Web application' client type
    with a fixed backend redirect URI — assert the implementation actually
    matches that, not an installed/Desktop-app flow. Desktop clients cannot
    use incremental authorization, which this flow relies on."""
    from app import integration_service
    from app.credential_store import FakeCredentialStore
    from app.oauth_flow import OAuthFlowStore

    store = FakeCredentialStore()
    integration_service.store_client_credentials(store, "google_calendar", client_id="cid", client_secret="csecret")
    flow_store = OAuthFlowStore()
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
    )
    # A Desktop/installed-app client never sends a client_secret in the
    # token exchange and cannot use include_granted_scopes; this backend
    # does both, which only a Web application client type supports.
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fintegrations%2Fgoogle_calendar%2Foauth%2Fcallback" in result.authorization_url
    assert "include_granted_scopes=true" in result.authorization_url
