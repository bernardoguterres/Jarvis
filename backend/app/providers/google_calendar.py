"""Phase 9 (corrected): Google Calendar integration — OAuth Authorization
Code + PKCE against a Google **Web application** OAuth client (not
Desktop/installed — incremental authorization via
`include_granted_scopes=true` below is documented by Google as unsupported
for installed/Desktop clients), least-privilege incremental scopes, and a
normalized local read cache.

Read scopes requested by default:
  https://www.googleapis.com/auth/calendar.calendarlist.readonly
  https://www.googleapis.com/auth/calendar.events.readonly

Write scope (only ever requested when the user explicitly enables write,
via a fresh incremental-consent OAuth round trip — never silently upgraded):
  https://www.googleapis.com/auth/calendar.events.owned
  (write access to calendars the user OWNS only — never the broader
  calendar.events scope, which would also permit writing to any calendar
  merely shared with the user)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"

READ_SCOPES = (
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
)
WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"


class GoogleCalendarError(Exception):
    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass
class TokenResult:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str


@dataclass
class CalendarListEntry:
    external_id: str
    summary: str
    access_role: str
    is_owned: bool
    timezone: str | None


@dataclass
class NormalizedEvent:
    external_id: str
    title: str
    description: str | None
    location: str | None
    all_day: bool
    start_datetime: datetime | None
    end_datetime: datetime | None
    start_date: str | None
    end_date: str | None
    event_timezone: str | None
    etag: str | None
    source_updated_at: datetime | None


def build_authorization_url(
    *, client_id: str, redirect_uri: str, state: str, code_challenge: str, include_write_scope: bool
) -> str:
    scopes = list(READ_SCOPES) + ([WRITE_SCOPE] if include_write_scope else [])
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    query = httpx.QueryParams(params)
    return f"{AUTH_ENDPOINT}?{query}"


def exchange_code_for_tokens(
    *, client: httpx.Client, client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str
) -> TokenResult:
    response = client.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
    )
    if response.status_code != 200:
        raise GoogleCalendarError("token_exchange_failed", f"HTTP {response.status_code} from token endpoint")
    body = response.json()
    return TokenResult(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in", 3600),
        scope=body.get("scope", ""),
    )


def refresh_access_token(*, client: httpx.Client, client_id: str, client_secret: str, refresh_token: str) -> TokenResult:
    response = client.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    if response.status_code != 200:
        # Google's OAuth error body is {"error": "...", "error_description":
        # "..."} — a standard error CODE/description, never a credential
        # value, and safe to surface for real diagnosis (e.g.
        # "invalid_grant" means the refresh token itself was revoked,
        # which points somewhere completely different than a Keychain/
        # signing-identity issue).
        try:
            error_body = response.json()
            reason = error_body.get("error_description") or error_body.get("error") or "unknown"
        except ValueError:
            reason = "unparseable response body"
        raise GoogleCalendarError(
            "token_refresh_failed", f"HTTP {response.status_code} from token endpoint: {reason}"
        )
    body = response.json()
    return TokenResult(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),  # not always reissued
        expires_in=body.get("expires_in", 3600),
        scope=body.get("scope", ""),
    )


def revoke_token(*, client: httpx.Client, token: str) -> bool:
    response = client.post(REVOKE_ENDPOINT, data={"token": token})
    return response.status_code == 200


def list_calendars(*, client: httpx.Client, access_token: str) -> list[CalendarListEntry]:
    response = client.get(
        f"{API_BASE}/users/me/calendarList", headers={"Authorization": f"Bearer {access_token}"}
    )
    _raise_for_status(response)
    entries = []
    for item in response.json().get("items", []):
        entries.append(
            CalendarListEntry(
                external_id=item["id"],
                summary=item.get("summary", item["id"]),
                access_role=item.get("accessRole", "reader"),
                is_owned=item.get("accessRole") == "owner",
                timezone=item.get("timeZone"),
            )
        )
    return entries


def list_events(
    *, client: httpx.Client, access_token: str, calendar_id: str, time_min: datetime, time_max: datetime
) -> list[NormalizedEvent]:
    response = client.get(
        f"{API_BASE}/calendars/{quote(calendar_id, safe='')}/events",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "timeMin": time_min.astimezone(timezone.utc).isoformat(),
            "timeMax": time_max.astimezone(timezone.utc).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        },
    )
    _raise_for_status(response)
    return [_normalize_event(item) for item in response.json().get("items", [])]


def _normalize_event(item: dict[str, Any]) -> NormalizedEvent:
    start = item.get("start", {})
    end = item.get("end", {})
    all_day = "date" in start and "dateTime" not in start

    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    updated = item.get("updated")
    return NormalizedEvent(
        external_id=item["id"],
        title=item.get("summary", "(untitled)"),
        description=item.get("description"),
        location=item.get("location"),
        all_day=all_day,
        start_datetime=_parse_dt(start.get("dateTime")),
        end_datetime=_parse_dt(end.get("dateTime")),
        start_date=start.get("date"),
        end_date=end.get("date"),
        event_timezone=start.get("timeZone"),
        etag=item.get("etag"),
        source_updated_at=_parse_dt(updated),
    )


def create_event(
    *,
    client: httpx.Client,
    access_token: str,
    calendar_id: str,
    title: str,
    description: str | None,
    location: str | None,
    all_day: bool,
    start: str,
    end: str,
    timezone_name: str | None,
) -> str:
    """Returns the created event's external ID. `start`/`end` are either
    date strings (YYYY-MM-DD, all-day) or RFC3339 datetimes."""
    body: dict[str, Any] = {"summary": title}
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    if all_day:
        body["start"] = {"date": start}
        body["end"] = {"date": end}
    else:
        body["start"] = {"dateTime": start, "timeZone": timezone_name}
        body["end"] = {"dateTime": end, "timeZone": timezone_name}

    response = client.post(
        f"{API_BASE}/calendars/{quote(calendar_id, safe='')}/events",
        headers={"Authorization": f"Bearer {access_token}"},
        json=body,
    )
    _raise_for_status(response)
    return response.json()["id"]


def update_event(
    *,
    client: httpx.Client,
    access_token: str,
    calendar_id: str,
    event_id: str,
    title: str | None = None,
    description: str | None = None,
    location: str | None = None,
) -> None:
    body: dict[str, Any] = {}
    if title is not None:
        body["summary"] = title
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location

    response = client.patch(
        f"{API_BASE}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        headers={"Authorization": f"Bearer {access_token}"},
        json=body,
    )
    _raise_for_status(response)


def delete_event(*, client: httpx.Client, access_token: str, calendar_id: str, event_id: str) -> None:
    response = client.delete(
        f"{API_BASE}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id, safe='')}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if response.status_code not in (200, 204, 410):  # 410 Gone = already deleted
        _raise_for_status(response)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise GoogleCalendarError(f"http_{response.status_code}", f"Google Calendar API error {response.status_code}")
