"""Google Calendar provider — all HTTP mocked via httpx.MockTransport, no
real network calls. Covers timezone/all-day event normalization."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.providers import google_calendar as gcal


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_authorization_url_includes_pkce_and_state_and_read_scopes() -> None:
    url = gcal.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/cb", state="st4te", code_challenge="chal",
        include_write_scope=False,
    )
    assert "state=st4te" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "calendar.events.owned" not in url
    assert "calendar.readonly" in url or "calendar.events.readonly" in url


def test_authorization_url_includes_write_scope_only_when_requested() -> None:
    url = gcal.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/cb", state="s", code_challenge="c",
        include_write_scope=True,
    )
    assert "calendar.events.owned" in url


def test_exchange_code_for_tokens() -> None:
    client = _client(
        lambda r: httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "s1 s2"})
    )
    result = gcal.exchange_code_for_tokens(
        client=client, client_id="cid", client_secret="secret", code="abc", redirect_uri="http://x", code_verifier="v"
    )
    assert result.access_token == "at"
    assert result.refresh_token == "rt"
    assert result.scope == "s1 s2"


def test_exchange_code_for_tokens_failure_raises() -> None:
    client = _client(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(gcal.GoogleCalendarError):
        gcal.exchange_code_for_tokens(
            client=client, client_id="cid", client_secret="s", code="bad", redirect_uri="http://x", code_verifier="v"
        )


def test_list_calendars_marks_owned_vs_shared() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "primary", "summary": "Bernardo", "accessRole": "owner", "timeZone": "Europe/London"},
                    {"id": "shared@x.com", "summary": "Shared", "accessRole": "reader"},
                ]
            },
        )

    entries = gcal.list_calendars(client=_client(handler), access_token="at")
    assert entries[0].is_owned is True
    assert entries[1].is_owned is False


def test_list_events_normalizes_all_day_event() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ev1",
                        "summary": "Birthday",
                        "start": {"date": "2026-09-01"},
                        "end": {"date": "2026-09-02"},
                        "etag": "\"abc\"",
                    }
                ]
            },
        )

    events = gcal.list_events(
        client=_client(handler),
        access_token="at",
        calendar_id="primary",
        time_min=datetime(2026, 9, 1, tzinfo=timezone.utc),
        time_max=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    assert events[0].all_day is True
    assert events[0].start_date == "2026-09-01"
    assert events[0].start_datetime is None


def test_list_events_normalizes_timed_event_with_timezone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "ev2",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-09-01T09:00:00+01:00", "timeZone": "Europe/London"},
                        "end": {"dateTime": "2026-09-01T09:30:00+01:00", "timeZone": "Europe/London"},
                    }
                ]
            },
        )

    events = gcal.list_events(
        client=_client(handler),
        access_token="at",
        calendar_id="primary",
        time_min=datetime(2026, 9, 1, tzinfo=timezone.utc),
        time_max=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    assert events[0].all_day is False
    assert events[0].event_timezone == "Europe/London"
    assert events[0].start_datetime is not None


def test_create_event_returns_external_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"id": "new-event-id"})

    external_id = gcal.create_event(
        client=_client(handler),
        access_token="at",
        calendar_id="primary",
        title="Test",
        description=None,
        location=None,
        all_day=True,
        start="2026-09-01",
        end="2026-09-02",
        timezone_name=None,
    )
    assert external_id == "new-event-id"


def test_delete_event_treats_410_as_success() -> None:
    client = _client(lambda r: httpx.Response(410))
    gcal.delete_event(client=client, access_token="at", calendar_id="primary", event_id="gone")  # must not raise


def test_delete_event_raises_on_real_error() -> None:
    client = _client(lambda r: httpx.Response(403, json={"error": "forbidden"}))
    with pytest.raises(gcal.GoogleCalendarError):
        gcal.delete_event(client=client, access_token="at", calendar_id="primary", event_id="x")
