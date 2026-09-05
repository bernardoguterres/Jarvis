"""Phase 9 (corrected): OAuth connect/disconnect, manual sync, and
normalized caching for Google Calendar and Google Health — orchestrating
credential_store.py, oauth_flow.py, and
app/providers/{google_calendar,google_health}.py.

Both providers use a Google OAuth **Web application** client (not
Desktop/installed) — required because incremental authorization
(`include_granted_scopes=true`, used to add the Calendar write scope only
when Bernardo explicitly enables it) is documented by Google as unsupported
for installed/Desktop clients. The backend performs the authorization-code
exchange and owns a fixed callback endpoint per provider; see
docs/DECISIONS.md for the full rationale.

Every credential (client id/secret, access/refresh tokens, expiry) lives
only in the CredentialStore (Keychain in production, fake in tests) — never
in the returned dataclasses' string form reaching the API layer, never in
SQLite, never logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.credential_store import CredentialStore
from app.models_integrations import (
    CalendarCalendar,
    CalendarEventCache,
    GoogleHealthDailySummary,
    GoogleHealthSession,
    IntegrationConnection,
)
from app.oauth_flow import OAuthFlowError, OAuthFlowStore, pkce_challenge_from_verifier
from app.recall_index_service import sync_recall
from app.providers import google_health as gh_provider
from app.providers import google_calendar as gcal_provider

CALENDAR_SYNC_DAYS_PAST = 1
CALENDAR_SYNC_DAYS_FUTURE = 30
GOOGLE_HEALTH_SYNC_DAYS_BACK = 7
GOOGLE_HEALTH_MAX_DAYS_PER_SYNC = 31
TOKEN_REFRESH_SKEW = timedelta(minutes=5)


class IntegrationError(Exception):
    def __init__(self, code: str, summary: str, *, retry_after: int | None = None) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        # Seconds, when the underlying provider error carried a real
        # Retry-After value (currently only GoogleHealthError does) — the
        # scheduler (app/scheduler_service.py) honors this over its own
        # computed backoff when present.
        self.retry_after = retry_after


class IntegrationNotConfiguredError(IntegrationError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            "not_configured",
            f"No OAuth client credentials configured for {provider!r}. Run "
            f"`jarvis-cli configure-integration {provider} ...` first.",
        )


@dataclass
class OAuthStartResult:
    authorization_url: str


def _get_connection(session: Session, provider: str) -> IntegrationConnection:
    conn = session.get(IntegrationConnection, provider)
    if conn is None:
        conn = IntegrationConnection(provider=provider, status="disconnected", scopes_json="[]")
        session.add(conn)
        session.flush()
    return conn


def get_connection(session: Session, provider: str) -> IntegrationConnection:
    return _get_connection(session, provider)


def has_scope(session: Session, provider: str, scope: str) -> bool:
    """Checks the connection's actually-granted scopes (as returned by
    Google in the token response), never what was merely requested. Used to
    gate Calendar write capability — see capabilities.py and
    calendar_capability.py."""
    conn = session.get(IntegrationConnection, provider)
    if conn is None or conn.status != "connected":
        return False
    try:
        granted = json.loads(conn.scopes_json)
    except (json.JSONDecodeError, TypeError):
        return False
    return scope in granted


def store_client_credentials(
    store: CredentialStore, provider: str, *, client_id: str, client_secret: str | None
) -> None:
    store.set(provider, "client_id", client_id)
    if client_secret is not None:
        store.set(provider, "client_secret", client_secret)


def _get_client_credentials(store: CredentialStore, provider: str) -> tuple[str, str | None]:
    client_id = store.get(provider, "client_id")
    if not client_id:
        raise IntegrationNotConfiguredError(provider)
    client_secret = store.get(provider, "client_secret")
    return client_id, client_secret


def _redirect_uri(base_url: str, provider: str) -> str:
    return f"{base_url}/api/integrations/{provider}/oauth/callback"


def begin_google_calendar_oauth(
    *, store: CredentialStore, flow_store: OAuthFlowStore, base_url: str, include_write_scope: bool
) -> OAuthStartResult:
    client_id, _ = _get_client_credentials(store, "google_calendar")
    redirect_uri = _redirect_uri(base_url, "google_calendar")
    flow = flow_store.start("google_calendar", redirect_uri)
    challenge = pkce_challenge_from_verifier(flow.code_verifier)
    url = gcal_provider.build_authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=flow.state,
        code_challenge=challenge,
        include_write_scope=include_write_scope,
    )
    return OAuthStartResult(authorization_url=url)


def begin_google_health_oauth(*, store: CredentialStore, flow_store: OAuthFlowStore, base_url: str) -> OAuthStartResult:
    client_id, _ = _get_client_credentials(store, "google_health")
    redirect_uri = _redirect_uri(base_url, "google_health")
    flow = flow_store.start("google_health", redirect_uri)
    challenge = pkce_challenge_from_verifier(flow.code_verifier)
    url = gh_provider.build_authorization_url(
        client_id=client_id, redirect_uri=redirect_uri, state=flow.state, code_challenge=challenge
    )
    return OAuthStartResult(authorization_url=url)


# The scopes each provider's own OAuth client can ever legitimately be
# granted. Google associates consent with the (user, Cloud project) pair,
# not (user, client_id) — confirmed live (D63, D65): a request from either
# client can come back carrying the OTHER integration's scopes when both
# share a project and `include_granted_scopes`/`prompt=consent` triggers a
# full re-affirmation of everything the project has ever been granted.
# Filtering the response to only the scopes this provider's own code ever
# uses is what prevents that cross-contamination from ever reaching
# storage, regardless of what Google's redirect happens to include.
_GOOGLE_CALENDAR_ALLOWED_SCOPES = frozenset(gcal_provider.READ_SCOPES) | {gcal_provider.WRITE_SCOPE}
_GOOGLE_HEALTH_ALLOWED_SCOPES = frozenset(gh_provider.READ_SCOPES)

_PROVIDER_ALLOWED_SCOPES = {
    "google_calendar": _GOOGLE_CALENDAR_ALLOWED_SCOPES,
    "google_health": _GOOGLE_HEALTH_ALLOWED_SCOPES,
}


def _normalize_granted_scopes(provider: str, raw_scope: str, existing_scopes_json: str) -> list[str]:
    """Filters Google's returned scope string down to only the scopes this
    provider's own OAuth client legitimately requests, then falls back to
    the previously-stored scopes if that filtering leaves nothing at all
    (never overwrite a real, working scope grant with an empty one just
    because this particular response was entirely cross-contaminated)."""
    allowed = _PROVIDER_ALLOWED_SCOPES[provider]
    granted = [s for s in raw_scope.split(" ") if s in allowed] if raw_scope else []
    if granted:
        return granted
    try:
        existing = json.loads(existing_scopes_json)
    except (json.JSONDecodeError, TypeError):
        existing = []
    return existing if isinstance(existing, list) else []


def _persist_oauth_connection(
    session: Session,
    store: CredentialStore,
    *,
    provider: str,
    access_token: str,
    refresh_token: str | None,
    expires_in: int,
    raw_scope: str,
) -> IntegrationConnection:
    """Shared, safe callback-completion path for both providers: Keychain
    is written first (never with a null/empty value replacing something
    real — `_store_tokens` already skips a missing refresh_token rather
    than deleting the stored one), and the database row is only marked
    connected after that succeeds. A Keychain failure here must produce a
    truthful error, never a false "connected" page or a DB/Keychain state
    that disagree with each other."""
    conn = _get_connection(session, provider)
    try:
        _store_tokens(store, provider, access_token, refresh_token, expires_in)
    except Exception as exc:
        raise IntegrationError("credential_store_failed", f"Could not persist {provider} credentials: {exc}") from exc

    conn.status = "connected"
    conn.scopes_json = json.dumps(_normalize_granted_scopes(provider, raw_scope, conn.scopes_json))
    conn.connected_at = datetime.now(timezone.utc)
    conn.last_error = None
    session.commit()
    session.refresh(conn)
    return conn


def handle_google_calendar_callback(
    session: Session,
    *,
    store: CredentialStore,
    flow_store: OAuthFlowStore,
    http_client: httpx.Client,
    code: str,
    state: str,
) -> IntegrationConnection:
    try:
        flow = flow_store.consume(state, provider="google_calendar")
    except OAuthFlowError as exc:
        raise IntegrationError("oauth_state_invalid", str(exc)) from exc

    client_id, client_secret = _get_client_credentials(store, "google_calendar")
    if not client_secret:
        raise IntegrationNotConfiguredError("google_calendar")

    tokens = gcal_provider.exchange_code_for_tokens(
        client=http_client,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=flow.redirect_uri,
        code_verifier=flow.code_verifier,
    )
    return _persist_oauth_connection(
        session,
        store,
        provider="google_calendar",
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        raw_scope=tokens.scope,
    )


def handle_google_health_callback(
    session: Session,
    *,
    store: CredentialStore,
    flow_store: OAuthFlowStore,
    http_client: httpx.Client,
    code: str,
    state: str,
) -> IntegrationConnection:
    try:
        flow = flow_store.consume(state, provider="google_health")
    except OAuthFlowError as exc:
        raise IntegrationError("oauth_state_invalid", str(exc)) from exc

    client_id, client_secret = _get_client_credentials(store, "google_health")
    if not client_secret:
        raise IntegrationNotConfiguredError("google_health")
    tokens = gh_provider.exchange_code_for_tokens(
        client=http_client,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=flow.redirect_uri,
        code_verifier=flow.code_verifier,
    )
    return _persist_oauth_connection(
        session,
        store,
        provider="google_health",
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        raw_scope=tokens.scope,
    )


def _store_tokens(store: CredentialStore, provider: str, access_token: str, refresh_token: str | None, expires_in: int) -> None:
    store.set(provider, "access_token", access_token)
    if refresh_token is not None:
        store.set(provider, "refresh_token", refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    store.set(provider, "access_token_expires_at", expires_at.isoformat())


def ensure_fresh_access_token(
    session: Session, store: CredentialStore, http_client: httpx.Client, provider: str
) -> str:
    access_token = store.get(provider, "access_token")
    refresh_token = store.get(provider, "refresh_token")
    expires_at_raw = store.get(provider, "access_token_expires_at")
    if not access_token or not refresh_token:
        raise IntegrationError("disconnected", f"{provider} is not connected.")

    expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else datetime.now(timezone.utc)
    if datetime.now(timezone.utc) + TOKEN_REFRESH_SKEW < expires_at:
        return access_token

    client_id, client_secret = _get_client_credentials(store, provider)
    try:
        if provider == "google_calendar":
            if not client_secret:
                raise IntegrationNotConfiguredError(provider)
            tokens = gcal_provider.refresh_access_token(
                client=http_client, client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
            )
        elif provider == "google_health":
            if not client_secret:
                raise IntegrationNotConfiguredError(provider)
            tokens = gh_provider.refresh_access_token(
                client=http_client, client_id=client_id, client_secret=client_secret, refresh_token=refresh_token
            )
        else:
            raise IntegrationError("unknown_provider", provider)
    except (gcal_provider.GoogleCalendarError, gh_provider.GoogleHealthError) as exc:
        conn = _get_connection(session, provider)
        conn.status = "error"
        conn.last_error = str(exc)[:500]
        session.commit()
        raise IntegrationError("token_refresh_failed", str(exc), retry_after=getattr(exc, "retry_after", None)) from exc

    _store_tokens(store, provider, tokens.access_token, tokens.refresh_token or refresh_token, tokens.expires_in)
    return tokens.access_token


def disconnect(session: Session, store: CredentialStore, http_client: httpx.Client, provider: str) -> IntegrationConnection:
    access_token = store.get(provider, "access_token")
    client_id, client_secret = None, None
    try:
        client_id, client_secret = _get_client_credentials(store, provider)
    except IntegrationNotConfiguredError:
        pass

    if access_token:
        try:
            if provider == "google_calendar":
                gcal_provider.revoke_token(client=http_client, token=access_token)
            elif provider == "google_health":
                gh_provider.revoke_token(client=http_client, token=access_token)
        except Exception:
            pass  # best-effort revocation — local disconnect must still proceed

    store.delete_all(provider, ["access_token", "refresh_token", "access_token_expires_at", "user_id"])

    conn = _get_connection(session, provider)
    conn.status = "disconnected"
    conn.scopes_json = "[]"
    conn.last_error = None
    session.commit()
    session.refresh(conn)
    return conn


def sync_google_calendar(
    session: Session, store: CredentialStore, http_client: httpx.Client, *, selected_only: bool = True
) -> IntegrationConnection:
    conn = _get_connection(session, "google_calendar")
    try:
        access_token = ensure_fresh_access_token(session, store, http_client, "google_calendar")

        entries = gcal_provider.list_calendars(client=http_client, access_token=access_token)
        seen_external_ids = set()
        for entry in entries:
            seen_external_ids.add(entry.external_id)
            existing = session.execute(
                select(CalendarCalendar).where(CalendarCalendar.external_calendar_id == entry.external_id)
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    CalendarCalendar(
                        external_calendar_id=entry.external_id,
                        summary=entry.summary,
                        access_role=entry.access_role,
                        is_owned=entry.is_owned,
                        timezone=entry.timezone,
                        selected=False,
                    )
                )
            else:
                existing.summary = entry.summary
                existing.access_role = entry.access_role
                existing.is_owned = entry.is_owned
                existing.timezone = entry.timezone
        session.flush()

        calendars_to_sync = session.execute(
            select(CalendarCalendar).where(CalendarCalendar.selected.is_(True))
            if selected_only
            else select(CalendarCalendar)
        ).scalars().all()

        time_min = datetime.now(timezone.utc) - timedelta(days=CALENDAR_SYNC_DAYS_PAST)
        time_max = datetime.now(timezone.utc) + timedelta(days=CALENDAR_SYNC_DAYS_FUTURE)

        for calendar in calendars_to_sync:
            events = gcal_provider.list_events(
                client=http_client,
                access_token=access_token,
                calendar_id=calendar.external_calendar_id,
                time_min=time_min,
                time_max=time_max,
            )
            for event in events:
                existing_event = session.execute(
                    select(CalendarEventCache).where(
                        CalendarEventCache.calendar_id == calendar.id,
                        CalendarEventCache.external_event_id == event.external_id,
                    )
                ).scalar_one_or_none()
                start_date_val = date.fromisoformat(event.start_date) if event.start_date else None
                end_date_val = date.fromisoformat(event.end_date) if event.end_date else None
                if existing_event is None:
                    existing_event = CalendarEventCache(calendar_id=calendar.id, external_event_id=event.external_id)
                    session.add(existing_event)
                existing_event.title = event.title
                existing_event.description = event.description
                existing_event.location = event.location
                existing_event.all_day = event.all_day
                existing_event.start_datetime = event.start_datetime
                existing_event.end_datetime = event.end_datetime
                existing_event.start_date = start_date_val
                existing_event.end_date = end_date_val
                existing_event.event_timezone = event.event_timezone
                existing_event.etag = event.etag
                existing_event.source_updated_at = event.source_updated_at
                existing_event.fetched_at = datetime.now(timezone.utc)
                session.flush()
                sync_recall(session, "calendar_event", existing_event.id)

        conn.last_sync_at = datetime.now(timezone.utc)
        conn.last_sync_status = "ok"
        conn.last_error = None
        session.commit()
    except (IntegrationError, gcal_provider.GoogleCalendarError, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        conn.last_sync_at = datetime.now(timezone.utc)
        conn.last_sync_status = "error"
        conn.last_error = str(exc)[:500]
        session.commit()
        # Normalize to IntegrationError at this service boundary — the
        # router only ever catches IntegrationError. A bare re-raise here
        # previously let a raw GoogleCalendarError escape as an unhandled
        # 500 instead of a clean 502; see GoogleHealthError's identical bug
        # below, found live during Phase 9 acceptance (docs/DECISIONS.md D62).
        # KeyError/IndexError/TypeError/ValueError are also caught here as a
        # whole-sync backstop against a malformed/unexpected Google Calendar
        # response shape (e.g. an event missing "id") that would otherwise
        # raise unprotected out of `_normalize_event` and escape as an
        # unhandled 500 rather than a clean, recorded sync failure — a real
        # gap found during the Phase-11-adjacent reliability audit, D83.
        if isinstance(exc, IntegrationError):
            raise
        raise IntegrationError(getattr(exc, "code", "sync_failed"), str(exc), retry_after=getattr(exc, "retry_after", None)) from exc
    session.refresh(conn)
    return conn


_DAILY_SUMMARY_FIELDS = (
    "steps",
    "distance_km",
    "floors",
    "active_zone_minutes",
    "active_calories_kcal",
    "calories_out",
    "heart_rate_avg_bpm",
    "heart_rate_min_bpm",
    "heart_rate_max_bpm",
    "resting_heart_rate",
    "hrv_daily_rmssd_ms",
    "oxygen_saturation_avg_percent",
    "respiratory_rate_breaths_per_min",
    "vo2_max",
    "weight_kg",
    "weight_source",
    "body_fat_percent",
    "blood_glucose_mg_dl",
    "sleep_duration_ms",
    "sleep_minutes_asleep",
    "sleep_efficiency",
    "sleep_type",
)


def sync_google_health(
    session: Session, store: CredentialStore, http_client: httpx.Client, *, days_back: int = GOOGLE_HEALTH_SYNC_DAYS_BACK
) -> IntegrationConnection:
    days_back = max(1, min(days_back, GOOGLE_HEALTH_MAX_DAYS_PER_SYNC))
    conn = _get_connection(session, "google_health")
    try:
        access_token = ensure_fresh_access_token(session, store, http_client, "google_health")

        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=days_back - 1)
        end_date = today + timedelta(days=1)  # dailyRollUp range end is exclusive
        result = gh_provider.fetch_health_data(
            client=http_client, access_token=access_token, start_date=start_date, end_date=end_date
        )

        for day, summary in result.summaries.items():
            existing = session.execute(
                select(GoogleHealthDailySummary).where(GoogleHealthDailySummary.date == day)
            ).scalar_one_or_none()
            if existing is None:
                existing = GoogleHealthDailySummary(date=day)
                session.add(existing)
            # Only overwrite a field when this sync actually produced a
            # value — a metric that failed or had no data this run must not
            # wipe out a previously-synced value for the same day.
            for field_name in _DAILY_SUMMARY_FIELDS:
                new_value = getattr(summary, field_name, None)
                if new_value is not None:
                    setattr(existing, field_name, new_value)
            if summary.source_platforms:
                existing.source_platforms_json = json.dumps(sorted(summary.source_platforms))
            existing.fetched_at = datetime.now(timezone.utc)

        for record in result.sessions:
            existing_session = session.execute(
                select(GoogleHealthSession).where(
                    GoogleHealthSession.session_type == record.session_type,
                    GoogleHealthSession.external_id == record.external_id,
                )
            ).scalar_one_or_none()
            if existing_session is None:
                existing_session = GoogleHealthSession(session_type=record.session_type, external_id=record.external_id)
                session.add(existing_session)
            existing_session.start_time = record.start_time
            existing_session.end_time = record.end_time
            existing_session.activity_type = record.activity_type
            existing_session.calories_kcal = record.calories_kcal
            existing_session.distance_km = record.distance_km
            existing_session.average_heart_rate_bpm = record.average_heart_rate_bpm
            existing_session.minutes_asleep = record.minutes_asleep
            existing_session.minutes_awake = record.minutes_awake
            existing_session.stages_json = json.dumps(record.stages) if record.stages else None
            existing_session.source_platform = record.source_platform
            existing_session.source_device = record.source_device
            existing_session.fetched_at = datetime.now(timezone.utc)

        if result.partial_failures:
            conn.last_sync_status = "partial"
            conn.last_error = "; ".join(f"{k}: {v}" for k, v in result.partial_failures.items())[:500]
        else:
            conn.last_sync_status = "ok"
            conn.last_error = None
        conn.last_sync_at = datetime.now(timezone.utc)
        session.commit()
    except (IntegrationError, gh_provider.GoogleHealthError, KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        conn.last_sync_at = datetime.now(timezone.utc)
        conn.last_sync_status = "error"
        conn.last_error = str(exc)[:500]
        session.commit()
        # Normalize to IntegrationError — see the matching fix in
        # sync_google_calendar above and docs/DECISIONS.md D62. A bare
        # re-raise here let a raw GoogleHealthError escape past the
        # router's `except IntegrationError`, surfacing an unhandled 500
        # instead of a clean 502 during live Phase 9 acceptance.
        # KeyError/IndexError/TypeError/ValueError are also caught here as a
        # whole-sync backstop — `fetch_health_data` already isolates a
        # malformed single data point per-metric (D83), but this is the
        # final backstop for anything genuinely unforeseen elsewhere in the
        # DB-write loop below it (e.g. an unexpected None reaching a
        # non-nullable column).
        if isinstance(exc, IntegrationError):
            raise
        raise IntegrationError(getattr(exc, "code", "sync_failed"), str(exc), retry_after=getattr(exc, "retry_after", None)) from exc
    session.refresh(conn)
    return conn
