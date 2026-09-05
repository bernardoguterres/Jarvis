"""Full OAuth begin -> callback -> sync -> disconnect flow, using a fake
credential store and mocked httpx — no real Google Calendar/Health calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy.orm import Session

from app import integration_service
from app.credential_store import FakeCredentialStore
from app.oauth_flow import OAuthFlowStore


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _configure(store: FakeCredentialStore, provider: str) -> None:
    integration_service.store_client_credentials(store, provider, client_id="cid", client_secret="csecret")


def test_begin_oauth_requires_configuration(db_session: Session) -> None:
    store = FakeCredentialStore()
    flow_store = OAuthFlowStore()
    with pytest.raises(integration_service.IntegrationNotConfiguredError):
        integration_service.begin_google_calendar_oauth(
            store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
        )


def test_begin_oauth_returns_state_bound_url() -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
    )
    assert "accounts.google.com" in result.authorization_url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fintegrations%2Fgoogle_calendar%2Foauth%2Fcallback" in result.authorization_url


def test_full_google_calendar_connect_flow(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
    )
    state = httpx.QueryParams(httpx.URL(result.authorization_url).query.decode())["state"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": "calendar.readonly"})

    conn = integration_service.handle_google_calendar_callback(
        db_session, store=store, flow_store=flow_store, http_client=_client(handler), code="authcode", state=state
    )
    assert conn.status == "connected"
    assert store.get("google_calendar", "access_token") == "AT1"
    assert store.get("google_calendar", "refresh_token") == "RT1"


_CAL_READ_SCOPES = "https://www.googleapis.com/auth/calendar.calendarlist.readonly https://www.googleapis.com/auth/calendar.events.readonly"
_CAL_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
_HEALTH_SCOPES = (
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly "
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly "
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly"
)


def _do_callback(db_session, store, flow_store, *, include_write_scope, response_json):
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=include_write_scope
    )
    state = httpx.QueryParams(httpx.URL(result.authorization_url).query.decode())["state"]
    return integration_service.handle_google_calendar_callback(
        db_session,
        store=store,
        flow_store=flow_store,
        http_client=_client(lambda r: httpx.Response(200, json=response_json)),
        code="authcode",
        state=state,
    )


def test_initial_oauth_response_with_refresh_token_is_stored(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    conn = _do_callback(
        db_session, store, flow_store, include_write_scope=False,
        response_json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _CAL_READ_SCOPES},
    )
    assert conn.status == "connected"
    assert store.get("google_calendar", "refresh_token") == "RT1"
    assert json.loads(conn.scopes_json) == _CAL_READ_SCOPES.split(" ")


def test_incremental_response_omitting_refresh_token_preserves_existing_one(db_session: Session) -> None:
    """The real, confirmed bug this fixes is scope corruption, not this
    specific refresh-token-loss hypothesis — but `_store_tokens` already
    guarded this correctly (skips the Keychain write entirely when the
    response omits refresh_token), and this proves it stays that way."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    _do_callback(
        db_session, store, flow_store, include_write_scope=False,
        response_json={"access_token": "AT1", "refresh_token": "RT-ORIGINAL", "expires_in": 3600, "scope": _CAL_READ_SCOPES},
    )
    assert store.get("google_calendar", "refresh_token") == "RT-ORIGINAL"

    # Incremental response omits refresh_token entirely (a real, normal
    # Google behavior when the account already has an active grant).
    conn = _do_callback(
        db_session, store, flow_store, include_write_scope=True,
        response_json={"access_token": "AT2", "expires_in": 3600, "scope": _CAL_READ_SCOPES + " " + _CAL_WRITE_SCOPE},
    )
    assert store.get("google_calendar", "refresh_token") == "RT-ORIGINAL"
    assert store.get("google_calendar", "access_token") == "AT2"
    assert conn.status == "connected"


def test_incremental_response_with_replacement_refresh_token_updates_it(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    _do_callback(
        db_session, store, flow_store, include_write_scope=False,
        response_json={"access_token": "AT1", "refresh_token": "RT-ORIGINAL", "expires_in": 3600, "scope": _CAL_READ_SCOPES},
    )
    _do_callback(
        db_session, store, flow_store, include_write_scope=True,
        response_json={"access_token": "AT2", "refresh_token": "RT-NEW", "expires_in": 3600, "scope": _CAL_READ_SCOPES + " " + _CAL_WRITE_SCOPE},
    )
    assert store.get("google_calendar", "refresh_token") == "RT-NEW"


def test_granted_read_scopes_plus_write_scope_persisted_correctly(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    conn = _do_callback(
        db_session, store, flow_store, include_write_scope=True,
        response_json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _CAL_READ_SCOPES + " " + _CAL_WRITE_SCOPE},
    )
    granted = json.loads(conn.scopes_json)
    assert set(granted) == set(_CAL_READ_SCOPES.split(" ")) | {_CAL_WRITE_SCOPE}


def test_cross_provider_scope_contamination_is_filtered_out(db_session: Session) -> None:
    """The real, confirmed root cause: Google can return the union of both
    integrations' scopes on a single callback when they share a Cloud
    project (D63/D65) — including, on this account, Health's 3 scopes
    appearing on a Calendar callback with the write scope never granted at
    all. The stored scopes must never include scopes that don't belong to
    this provider."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    conn = _do_callback(
        db_session, store, flow_store, include_write_scope=True,
        response_json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _HEALTH_SCOPES + " " + _CAL_READ_SCOPES},
    )
    granted = json.loads(conn.scopes_json)
    assert set(granted) == set(_CAL_READ_SCOPES.split(" "))
    for health_scope in _HEALTH_SCOPES.split(" "):
        assert health_scope not in granted


def test_entirely_contaminated_response_falls_back_to_previously_stored_scopes(db_session: Session) -> None:
    """If a callback's scope string contains nothing at all belonging to
    this provider (a degenerate case), the previously-stored, real scope
    grant must be preserved rather than overwritten with an empty list."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()

    _do_callback(
        db_session, store, flow_store, include_write_scope=False,
        response_json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _CAL_READ_SCOPES},
    )
    conn = _do_callback(
        db_session, store, flow_store, include_write_scope=False,
        response_json={"access_token": "AT2", "refresh_token": "RT1", "expires_in": 3600, "scope": _HEALTH_SCOPES},
    )
    assert json.loads(conn.scopes_json) == _CAL_READ_SCOPES.split(" ")


def test_credential_store_failure_cannot_produce_a_connected_database_row(db_session: Session) -> None:
    class _FailingStore(FakeCredentialStore):
        def set(self, provider: str, key: str, value: str) -> None:
            if key == "access_token":
                raise RuntimeError("simulated Keychain write failure")
            super().set(provider, key, value)

    store = _FailingStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
    )
    state = httpx.QueryParams(httpx.URL(result.authorization_url).query.decode())["state"]

    with pytest.raises(integration_service.IntegrationError):
        integration_service.handle_google_calendar_callback(
            db_session,
            store=store,
            flow_store=flow_store,
            http_client=_client(lambda r: httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _CAL_READ_SCOPES})),
            code="authcode",
            state=state,
        )

    conn = integration_service.get_connection(db_session, "google_calendar")
    assert conn.status != "connected"


def test_google_health_connection_untouched_by_a_calendar_callback(db_session: Session) -> None:
    """Regardless of what scopes Google's redirect includes, a Calendar
    callback must never read, write, or otherwise touch Google Health's
    own Keychain entries or database connection row."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    _configure(store, "google_health")
    store.set("google_health", "access_token", "HEALTH-AT-UNCHANGED")
    store.set("google_health", "refresh_token", "HEALTH-RT-UNCHANGED")
    health_conn_before = integration_service.get_connection(db_session, "google_health")
    health_conn_before.status = "connected"
    health_conn_before.scopes_json = json.dumps(_HEALTH_SCOPES.split(" "))
    db_session.commit()

    flow_store = OAuthFlowStore()
    _do_callback(
        db_session, store, flow_store, include_write_scope=True,
        response_json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": _HEALTH_SCOPES + " " + _CAL_READ_SCOPES},
    )

    assert store.get("google_health", "access_token") == "HEALTH-AT-UNCHANGED"
    assert store.get("google_health", "refresh_token") == "HEALTH-RT-UNCHANGED"
    health_conn_after = integration_service.get_connection(db_session, "google_health")
    assert health_conn_after.status == "connected"
    assert json.loads(health_conn_after.scopes_json) == _HEALTH_SCOPES.split(" ")


def test_callback_rejects_replayed_state(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    flow_store = OAuthFlowStore()
    result = integration_service.begin_google_calendar_oauth(
        store=store, flow_store=flow_store, base_url="http://127.0.0.1:8000", include_write_scope=False
    )
    state = httpx.QueryParams(httpx.URL(result.authorization_url).query.decode())["state"]
    handler = lambda r: httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": "s"})

    integration_service.handle_google_calendar_callback(
        db_session, store=store, flow_store=flow_store, http_client=_client(handler), code="c1", state=state
    )
    with pytest.raises(integration_service.IntegrationError):
        integration_service.handle_google_calendar_callback(
            db_session, store=store, flow_store=flow_store, http_client=_client(handler), code="c2", state=state
        )


def test_disconnect_removes_credentials_and_sets_status(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")

    conn = integration_service.disconnect(db_session, store, _client(lambda r: httpx.Response(200)), "google_calendar")
    assert conn.status == "disconnected"
    assert store.get("google_calendar", "access_token") is None
    assert store.get("google_calendar", "refresh_token") is None


def test_ensure_fresh_access_token_refreshes_when_near_expiry(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "OLD")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set(
        "google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600})

    token = integration_service.ensure_fresh_access_token(db_session, store, _client(handler), "google_calendar")
    assert token == "NEW"
    assert store.get("google_calendar", "refresh_token") == "RT2"


def test_ensure_fresh_access_token_reuses_valid_token(db_session: Session) -> None:
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "STILL-GOOD")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set(
        "google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the token endpoint when the token is still fresh")

    token = integration_service.ensure_fresh_access_token(db_session, store, _client(handler), "google_calendar")
    assert token == "STILL-GOOD"


def test_sync_google_calendar_populates_cache(db_session: Session) -> None:
    from app.models_integrations import CalendarCalendar

    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def handler(request: httpx.Request) -> httpx.Response:
        if "calendarList" in request.url.path:
            return httpx.Response(200, json={"items": [{"id": "primary", "summary": "Bernardo", "accessRole": "owner"}]})
        if "/events" in request.url.path:
            return httpx.Response(200, json={"items": []})
        raise AssertionError(request.url.path)

    integration_service.sync_google_calendar(db_session, store, _client(handler))
    calendars = db_session.query(CalendarCalendar).all()
    assert len(calendars) == 1
    assert calendars[0].summary == "Bernardo"
    assert calendars[0].is_owned is True


def test_sync_google_calendar_normalizes_provider_error_to_integration_error(db_session: Session) -> None:
    """Real bug found live during Phase 9 acceptance: a raw
    GoogleCalendarError escaping sync_google_calendar bypassed the router's
    `except IntegrationError`, surfacing an unhandled 500 instead of a clean
    502 (see docs/DECISIONS.md D62)."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    with pytest.raises(integration_service.IntegrationError):
        integration_service.sync_google_calendar(db_session, store, _client(handler))


def _empty_health_handler(request: httpx.Request) -> httpx.Response:
    if "dataPoints:dailyRollUp" in request.url.path:
        return httpx.Response(200, json={"rollupDataPoints": []})
    return httpx.Response(200, json={"dataPoints": []})


def test_sync_google_health_populates_cache(db_session: Session) -> None:
    from app.models_integrations import GoogleHealthDailySummary

    store = FakeCredentialStore()
    _configure(store, "google_health")
    store.set("google_health", "access_token", "AT1")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    today = datetime.now(timezone.utc).date()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.fitbit.com" not in str(request.url)
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "rollupDataPoints": [
                        {
                            "civilStartTime": {"date": {"year": today.year, "month": today.month, "day": today.day}},
                            "steps": {"countSum": "1234"},
                        }
                    ]
                },
            )
        return _empty_health_handler(request)

    integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)
    rows = db_session.query(GoogleHealthDailySummary).all()
    assert len(rows) >= 1
    assert any(r.steps == 1234 for r in rows)


def test_sync_google_health_is_idempotent_across_repeated_syncs(db_session: Session) -> None:
    """Repeated syncs with identical upstream data must not duplicate rows
    — a daily summary is keyed by date, a session by (session_type,
    external_id), both enforced by a real DB unique constraint."""
    from app.models_integrations import GoogleHealthDailySummary, GoogleHealthSession

    store = FakeCredentialStore()
    _configure(store, "google_health")
    store.set("google_health", "access_token", "AT1")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    today = datetime.now(timezone.utc).date()

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "rollupDataPoints": [
                        {
                            "civilStartTime": {"date": {"year": today.year, "month": today.month, "day": today.day}},
                            "steps": {"countSum": "5000"},
                        }
                    ]
                },
            )
        if "dataTypes/sleep/dataPoints" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dataPoints": [
                        {
                            "name": "users/me/dataTypes/sleep/dataPoints/idem-1",
                            "dataSource": {"platform": "FITBIT"},
                            "sleep": {
                                "interval": {"startTime": "2026-08-25T22:00:00Z", "endTime": "2026-08-26T06:00:00Z"},
                                "type": "STAGES",
                                "stages": [{"type": "LIGHT", "startTime": "2026-08-25T22:00:00Z", "endTime": "2026-08-26T06:00:00Z"}],
                            },
                        }
                    ]
                },
            )
        return _empty_health_handler(request)

    integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)
    integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)

    summaries = db_session.query(GoogleHealthDailySummary).filter(GoogleHealthDailySummary.date == today).all()
    sessions = db_session.query(GoogleHealthSession).filter(GoogleHealthSession.external_id == "users/me/dataTypes/sleep/dataPoints/idem-1").all()
    assert len(summaries) == 1
    assert summaries[0].steps == 5000
    assert len(sessions) == 1


def test_sync_google_health_records_partial_status_without_aborting_on_metric_failure(db_session: Session) -> None:
    """Missing/unsupported data for a given account is normal — one
    metric's real API failure must not abort the sync, and must be visible
    as a "partial" status rather than a silently-successful "ok"."""
    store = FakeCredentialStore()
    _configure(store, "google_health")
    store.set("google_health", "access_token", "AT1")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(400)
        return _empty_health_handler(request)

    conn = integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)
    assert conn.last_sync_status == "partial"
    assert "steps" in (conn.last_error or "")


def test_sync_google_health_malformed_data_point_does_not_abort_other_metrics(db_session: Session) -> None:
    """D83 (reliability audit): several extract functions use
    `v.get("distance", {}).get("millimetersSum")` — `.get(key, {})` only
    substitutes the default when `key` is *absent*, not when it's present
    with an explicit JSON `null`. A real API returning `"distance": null`
    (valid JSON, a realistic malformed/partial-response shape) previously
    raised an unhandled AttributeError (`'NoneType' object has no attribute
    'get'`) that escaped `fetch_health_data` entirely, aborting the whole
    sync and discarding every other metric already successfully parsed in
    the same call — contradicting this integration's own documented "one
    metric's failure never aborts the rest" guarantee. Steps (a sibling
    metric fetched in the same dailyRollUp call) must still populate."""
    store = FakeCredentialStore()
    _configure(store, "google_health")
    store.set("google_health", "access_token", "AT1")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    today = datetime.now(timezone.utc).date()
    civil_time = {"civilStartTime": {"date": {"year": today.year, "month": today.month, "day": today.day}}}

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/distance/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": [{**civil_time, "distance": None}]})
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": [{**civil_time, "steps": {"countSum": "4321"}}]})
        return _empty_health_handler(request)

    from app.models_integrations import GoogleHealthDailySummary

    conn = integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)
    assert conn.last_sync_status == "partial"
    assert "distance" in (conn.last_error or "")

    rows = db_session.query(GoogleHealthDailySummary).filter(GoogleHealthDailySummary.date == today).all()
    assert len(rows) == 1
    assert rows[0].steps == 4321
    assert rows[0].distance_km is None


def test_sync_google_calendar_malformed_event_recorded_as_error_not_unhandled_exception(db_session: Session) -> None:
    """D83 (reliability audit): `_normalize_event` reads `item["id"]` with
    direct indexing — a genuinely malformed/truncated Calendar API response
    (an event object missing "id") previously raised an unhandled KeyError
    that escaped `sync_google_calendar`'s narrow `except (IntegrationError,
    GoogleCalendarError)` entirely, surfacing as an unhandled exception
    instead of the sync being recorded as a clean, sanitized failure like
    every other kind of sync error already is."""
    store = FakeCredentialStore()
    _configure(store, "google_calendar")
    store.set("google_calendar", "access_token", "AT1")
    store.set("google_calendar", "refresh_token", "RT1")
    store.set("google_calendar", "access_token_expires_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())

    def handler(request: httpx.Request) -> httpx.Response:
        if "calendarList" in request.url.path:
            return httpx.Response(200, json={"items": [{"id": "primary", "summary": "Bernardo", "accessRole": "owner"}]})
        if "/events" in request.url.path:
            return httpx.Response(200, json={"items": [{"summary": "Missing its id field"}]})
        raise AssertionError(request.url.path)

    with pytest.raises(integration_service.IntegrationError):
        integration_service.sync_google_calendar(db_session, store, _client(handler), selected_only=False)


def test_sync_google_health_normalizes_token_refresh_error_to_integration_error(db_session: Session) -> None:
    """Real bug found live during Phase 9 acceptance: a raw provider error
    escaping sync_google_health uncaught by the router's `except
    IntegrationError` produced an unhandled 500 (see docs/DECISIONS.md
    D62). Per-metric fetch failures are now handled per-metric (see the
    partial-status test above); this covers the remaining path that can
    still raise directly — a failed token refresh."""
    store = FakeCredentialStore()
    _configure(store, "google_health")
    store.set("google_health", "access_token", "OLD")
    store.set("google_health", "refresh_token", "RT1")
    store.set("google_health", "access_token_expires_at", (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)

    with pytest.raises(integration_service.IntegrationError):
        integration_service.sync_google_health(db_session, store, _client(handler), days_back=2)
