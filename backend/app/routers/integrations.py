"""Phase 9 (corrected): OAuth connect/disconnect/sync for Google Calendar
and Google Health (a general Google Health integration in the UI — reads
consented data that can originate from Fitbit, Pixel Watch, Health Connect,
Google Fit, or other connected sources; see docs/DECISIONS.md D64 for why
the legacy Fitbit Web API integration was replaced and the product
language was broadened beyond Fitbit-specific framing).

The OAuth callback endpoints are hit directly by the user's browser after
Google redirects back — they are loopback-only (this backend only ever
binds 127.0.0.1) and validated against the exact registered redirect URI.
They return a small static HTML page, not JSON.
"""

from __future__ import annotations

import html
import json
import logging
import math
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app import integration_service, scheduler_service
from app.credential_store import CredentialStore
from app.deps import get_backend_base_url, get_credential_store, get_db, get_http_client, get_oauth_flow_store
from app.models_integrations import (
    CalendarCalendar,
    CalendarEventCache,
    GoogleHealthDailySummary,
    GoogleHealthSession,
    IntegrationConnection,
)
from app.models_scheduler import IntegrationSyncRun
from app.oauth_flow import OAuthFlowStore
from app.providers.google_health import UNSUPPORTED_METRICS
from app.schemas_integrations import (
    CalendarCalendarRead,
    CalendarEventRead,
    CalendarSelectRequest,
    GoogleHealthDailySummaryRead,
    GoogleHealthMetricGroupStatus,
    GoogleHealthSessionRead,
    GoogleHealthSyncRequest,
    IntegrationConnectionRead,
    OAuthStartRequest,
    OAuthStartResponse,
)
from app.schemas_scheduler import IntegrationScheduleRead, IntegrationScheduleUpdateRequest, IntegrationSyncRunRead

logger = logging.getLogger("jarvis.routers.integrations")

router = APIRouter(tags=["integrations"])

_PROVIDERS = ("google_calendar", "google_health")


def _connection_to_read(conn: IntegrationConnection) -> IntegrationConnectionRead:
    return IntegrationConnectionRead(
        provider=conn.provider,
        status=conn.status,
        scopes=json.loads(conn.scopes_json),
        external_account_label=conn.external_account_label,
        connected_at=conn.connected_at,
        last_sync_at=conn.last_sync_at,
        last_sync_status=conn.last_sync_status,
        last_error=conn.last_error,
    )


_PROVIDER_LABELS = {"google_calendar": "Google Calendar", "google_health": "Google Health"}

# Same token *values* index.css defines (--accent-cyan-strong, --status-error,
# --bg-void, --bg-panel-sunken, --border-subtle, --text-primary/secondary/
# tertiary, --font-mono) — duplicated here as plain constants rather than
# imported, since this page is rendered by FastAPI, not bundled by Vite,
# and must never depend on the frontend build existing at all.
_TOKEN_CYAN = "#6fe9f2"
_TOKEN_ERROR = "#ff6b7a"
_TOKEN_BG_VOID = "#050308"
_TOKEN_BG_SUNKEN = "#0d0b18"
_TOKEN_BORDER_SUBTLE = "#29233f"
_TOKEN_TEXT_PRIMARY = "#f2effa"
_TOKEN_TEXT_SECONDARY = "#bcb6d8"
_TOKEN_TEXT_TERTIARY = "#85809f"
_TOKEN_FONT_MONO = 'ui-monospace, "SF Mono", Menlo, monospace'


def _diagnostic_ring_svg(accent: str, *, gapped: bool, animation_class: str) -> str:
    """A small echo of the frontend's diagnostic ring (see
    frontend/src/components/diagnostic/Diagnostic.tsx) — a segmented circle
    with one wedge cut away for a failure, whole for a success. Plain
    inline SVG so this page never depends on the frontend CSS bundle.
    `animation_class` (see `_callback_page`) is what actually gives it
    real, state-driven motion rather than sitting static."""
    segments = "".join(
        f'<path d="M50,50 L{50 + 38 * _cos(a)},{50 + 38 * _sin(a)} '
        f'A38,38 0 0,1 {50 + 38 * _cos(a + 22)},{50 + 38 * _sin(a + 22)} Z" '
        f'fill="{accent}" opacity="0.85" />'
        for a in range(0, 360, 45)
        if not (gapped and a == 180)
    )
    return (
        f'<svg width="88" height="88" viewBox="0 0 100 100" aria-hidden="true" class="diag-ring {animation_class}">{segments}'
        f'<circle cx="50" cy="50" r="16" fill="{_TOKEN_BG_SUNKEN}" stroke="{accent}" stroke-width="1.5" /></svg>'
    )


def _cos(deg: float) -> float:
    return math.cos(math.radians(deg))


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _callback_page(
    title: str,
    message: str,
    *,
    ok: bool = True,
    provider: str | None = None,
    micro_label: str | None = None,
    show_try_again: bool = False,
) -> HTMLResponse:
    # title/message can carry values Google or an exception controlled
    # (the callback's own `error` query param, or str(exc)) — always
    # HTML-escape before interpolating, since this page is served directly
    # to the browser that just followed the OAuth redirect.
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    safe_provider = html.escape(provider or "the provider")
    accent = _TOKEN_CYAN if ok else _TOKEN_ERROR
    label = html.escape(micro_label or ("CONNECTED" if ok else "CONNECTION FAULT"))
    # Success spins continuously and briskly — a real "it's working"
    # signal, like a gear happily running. Failure repeats a slow,
    # deliberate partial turn-and-stop cycle — reads as "it keeps trying
    # and stalling," never a continuous spin (which would wrongly read as
    # "still trying to complete right now") or a static image ("dead").
    ring_animation_class = "diag-ring-spin" if ok else "diag-ring-turn-stop"
    ring = _diagnostic_ring_svg(accent, gapped=not ok, animation_class=ring_animation_class)

    try_again_link = (
        f'<a href="/?open=integrations" class="secondary">Try connection again</a>' if show_try_again and not ok else ""
    )

    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{safe_title} — Jarvis</title>
        <style>
          :root {{ color-scheme: dark; }}
          body {{
            margin: 0; min-height: 100vh; display: flex; flex-direction: column;
            align-items: center; justify-content: center; gap: 1.25rem;
            font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
            background: {_TOKEN_BG_VOID}; color: {_TOKEN_TEXT_PRIMARY};
            text-align: center; padding: 1.5rem;
          }}
          .diag-code {{
            font-family: {_TOKEN_FONT_MONO}; font-size: 0.72rem; letter-spacing: 0.14em;
            text-transform: uppercase; color: {accent}; padding: 0.2rem 0.6rem;
            border: 1px solid {accent}; border-radius: 999px; display: inline-block;
          }}
          h1 {{ margin: 0.4rem 0 0; font-size: 1.3rem; letter-spacing: 0.02em; }}
          p {{ color: {_TOKEN_TEXT_SECONDARY}; line-height: 1.55; max-width: 44ch; margin: 0; }}
          .provider {{ color: {_TOKEN_TEXT_TERTIARY}; font-family: {_TOKEN_FONT_MONO}; font-size: 0.78rem; }}
          .actions {{ display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; margin-top: 0.5rem; }}
          a {{ color: {accent}; text-decoration: none; font-weight: 600; border: 1px solid {_TOKEN_BORDER_SUBTLE};
               border-radius: 8px; padding: 0.5rem 1rem; }}
          a:hover {{ border-color: {accent}; }}
          .diag-ring {{ transform-origin: 50% 50%; }}
          .diag-ring-spin {{ animation: diag-ring-spin 1.6s linear infinite; }}
          .diag-ring-turn-stop {{ animation: diag-ring-turn-stop 3.2s cubic-bezier(0.18, 0.8, 0.24, 1) infinite; }}
          @keyframes diag-ring-spin {{ to {{ transform: rotate(360deg); }} }}
          @keyframes diag-ring-turn-stop {{
            0%, 12% {{ transform: rotate(0deg); }}
            42% {{ transform: rotate(70deg); }}
            58% {{ transform: rotate(70deg); }}
            88%, 100% {{ transform: rotate(0deg); }}
          }}
          @media (prefers-reduced-motion: reduce) {{
            .diag-ring-spin, .diag-ring-turn-stop {{ animation: none; }}
          }}
        </style>
        </head><body>
        {ring}
        <div class="diag-code">{label}</div>
        <h1>{safe_title}</h1>
        <p class="provider">{safe_provider}</p>
        <p>{safe_message}</p>
        <div class="actions">
          <a href="/?open=integrations">Return to Integrations Centre</a>
          {try_again_link}
        </div>
        </body></html>"""
    )


@router.get("/api/integrations", response_model=list[IntegrationConnectionRead])
def list_integrations(db: Session = Depends(get_db)) -> list[IntegrationConnectionRead]:
    """Read-only — never touches the Keychain or mutates OAuth state.
    Each provider's row is fetched independently so one provider's
    unexpected failure can never take down the other provider's (truthful)
    status; a failure here is reported as `status="error"`, never silently
    reinterpreted as `"disconnected"`."""
    results = []
    for provider in _PROVIDERS:
        try:
            results.append(_connection_to_read(integration_service.get_connection(db, provider)))
        except Exception as exc:
            results.append(
                IntegrationConnectionRead(
                    provider=provider,
                    status="error",
                    scopes=[],
                    external_account_label=None,
                    connected_at=None,
                    last_sync_at=None,
                    last_sync_status=None,
                    last_error=f"Status check failed: {exc}"[:500],
                )
            )
    return results


def _open_in_system_browser(url: str) -> None:
    """Opens `url` in the real system browser, server-side, from this
    trusted local process — never through the native app's WebView/JS
    bridge, which was found unreliable for this exact purpose (Tauri only
    injects its IPC bridge into content loaded from its own trusted
    origin, and this app's real content loads from the same plain
    http://127.0.0.1 origin as everything else, not that trusted one).
    This makes "Connect" work identically whether Jarvis is running as
    the packaged native app or the `jarvisctl.sh` dev-mode browser
    workflow, with no special-casing needed anywhere in the frontend.

    A dedicated, narrowly-named function — not an inline
    `subprocess.Popen` call — specifically so tests can patch this one
    seam (see conftest.py's `_no_real_browser_open`) without patching the
    shared `subprocess` module wholesale, which would also break every
    other real subprocess use elsewhere (Hermes profile export, etc.)."""
    try:
        subprocess.Popen(["open", url])
    except OSError:
        logger.exception("Could not open the system browser for %s", url)


@router.post("/api/integrations/{provider}/connect", response_model=OAuthStartResponse)
def start_oauth(
    provider: str,
    payload: OAuthStartRequest,
    store: CredentialStore = Depends(get_credential_store),
    flow_store: OAuthFlowStore = Depends(get_oauth_flow_store),
    base_url: str = Depends(get_backend_base_url),
) -> OAuthStartResponse:
    try:
        if provider == "google_calendar":
            result = integration_service.begin_google_calendar_oauth(
                store=store, flow_store=flow_store, base_url=base_url, include_write_scope=payload.include_write_scope
            )
        elif provider == "google_health":
            result = integration_service.begin_google_health_oauth(store=store, flow_store=flow_store, base_url=base_url)
        else:
            raise HTTPException(status_code=404, detail="Unknown provider")
    except integration_service.IntegrationNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    _open_in_system_browser(result.authorization_url)

    return OAuthStartResponse(authorization_url=result.authorization_url)


@router.get("/api/integrations/google_calendar/oauth/callback")
def google_calendar_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    store: CredentialStore = Depends(get_credential_store),
    flow_store: OAuthFlowStore = Depends(get_oauth_flow_store),
    http_client=Depends(get_http_client),
) -> HTMLResponse:
    provider_label = _PROVIDER_LABELS["google_calendar"]
    if error or not code or not state:
        return _callback_page(
            "Connection cancelled",
            error or "The connection was not completed — no code or state was returned.",
            ok=False,
            provider=provider_label,
            micro_label="CONNECTION CANCELLED",
            show_try_again=True,
        )
    try:
        integration_service.handle_google_calendar_callback(
            db, store=store, flow_store=flow_store, http_client=http_client, code=code, state=state
        )
    except integration_service.IntegrationError as exc:
        return _callback_page("Connection failed", str(exc), ok=False, provider=provider_label)
    return _callback_page(
        "Connected",
        "You can close this tab and return to Jarvis.",
        provider=provider_label,
    )


@router.get("/api/integrations/google_health/oauth/callback")
def google_health_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
    store: CredentialStore = Depends(get_credential_store),
    flow_store: OAuthFlowStore = Depends(get_oauth_flow_store),
    http_client=Depends(get_http_client),
) -> HTMLResponse:
    provider_label = _PROVIDER_LABELS["google_health"]
    if error or not code or not state:
        return _callback_page(
            "Connection cancelled",
            error or "The connection was not completed — no code or state was returned.",
            ok=False,
            provider=provider_label,
            micro_label="CONNECTION CANCELLED",
            show_try_again=True,
        )
    try:
        integration_service.handle_google_health_callback(
            db, store=store, flow_store=flow_store, http_client=http_client, code=code, state=state
        )
    except integration_service.IntegrationError as exc:
        return _callback_page("Connection failed", str(exc), ok=False, provider=provider_label)
    return _callback_page(
        "Connected",
        "You can close this tab and return to Jarvis.",
        provider=provider_label,
    )


@router.post("/api/integrations/{provider}/disconnect", response_model=IntegrationConnectionRead)
def disconnect(
    provider: str,
    db: Session = Depends(get_db),
    store: CredentialStore = Depends(get_credential_store),
    http_client=Depends(get_http_client),
) -> IntegrationConnectionRead:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    conn = integration_service.disconnect(db, store, http_client, provider)
    return _connection_to_read(conn)


def _clock() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/api/integrations/google_calendar/sync", response_model=IntegrationConnectionRead)
def sync_google_calendar(
    db: Session = Depends(get_db), store: CredentialStore = Depends(get_credential_store), http_client=Depends(get_http_client)
) -> IntegrationConnectionRead:
    run = scheduler_service.run_provider_sync(db, store, http_client, "google_calendar", "manual", _clock)
    if run.outcome == "skipped":
        raise HTTPException(status_code=409, detail="An automatic sync for Google Calendar is already in progress.")
    if run.outcome == "failed":
        raise HTTPException(status_code=502, detail=run.reason or "Google Calendar sync failed.")
    return _connection_to_read(integration_service.get_connection(db, "google_calendar"))


@router.post("/api/integrations/google_health/sync", response_model=IntegrationConnectionRead)
def sync_google_health(
    payload: GoogleHealthSyncRequest,
    db: Session = Depends(get_db),
    store: CredentialStore = Depends(get_credential_store),
    http_client=Depends(get_http_client),
) -> IntegrationConnectionRead:
    run = scheduler_service.run_provider_sync(
        db, store, http_client, "google_health", "manual", _clock, days_back=payload.days_back
    )
    if run.outcome == "skipped":
        raise HTTPException(status_code=409, detail="An automatic sync for Google Health is already in progress.")
    if run.outcome == "failed":
        raise HTTPException(status_code=502, detail=run.reason or "Google Health sync failed.")
    return _connection_to_read(integration_service.get_connection(db, "google_health"))


@router.get("/api/integrations/{provider}/schedule", response_model=IntegrationScheduleRead)
def get_schedule(provider: str, db: Session = Depends(get_db)) -> IntegrationScheduleRead:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    schedule = scheduler_service.get_or_create_schedule(db, provider)
    db.commit()
    return IntegrationScheduleRead.model_validate(schedule, from_attributes=True)


@router.put("/api/integrations/{provider}/schedule", response_model=IntegrationScheduleRead)
def update_schedule(
    provider: str, payload: IntegrationScheduleUpdateRequest, db: Session = Depends(get_db)
) -> IntegrationScheduleRead:
    """An explicit local UI action — configuring how Jarvis manages its own
    local schedule metadata has no external side effect of its own, so
    this does not go through the Phase 8 proposal lifecycle (that governs
    actions with an external effect, like a Calendar write)."""
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    try:
        schedule = scheduler_service.set_schedule(
            db, provider, enabled=payload.enabled, interval_minutes=payload.interval_minutes, clock=_clock
        )
    except scheduler_service.ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IntegrationScheduleRead.model_validate(schedule, from_attributes=True)


@router.get("/api/integrations/{provider}/sync-history", response_model=list[IntegrationSyncRunRead])
def list_sync_history(provider: str, db: Session = Depends(get_db)) -> list[IntegrationSyncRunRead]:
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    rows = (
        db.query(IntegrationSyncRun)
        .filter(IntegrationSyncRun.provider == provider)
        .order_by(IntegrationSyncRun.started_at.desc())
        .limit(20)
        .all()
    )
    return [
        IntegrationSyncRunRead(
            id=r.id,
            provider=r.provider,
            trigger=r.trigger,
            started_at=r.started_at,
            completed_at=r.completed_at,
            outcome=r.outcome,
            reason=r.reason,
            result_summary=json.loads(r.result_summary_json) if r.result_summary_json else {},
        )
        for r in rows
    ]


@router.get("/api/integrations/google_calendar/calendars", response_model=list[CalendarCalendarRead])
def list_calendars(db: Session = Depends(get_db)) -> list[CalendarCalendarRead]:
    calendars = db.query(CalendarCalendar).order_by(CalendarCalendar.summary).all()
    return [CalendarCalendarRead.model_validate(c, from_attributes=True) for c in calendars]


@router.post("/api/integrations/google_calendar/calendars/{calendar_id}/select", response_model=CalendarCalendarRead)
def select_calendar(calendar_id: str, payload: CalendarSelectRequest, db: Session = Depends(get_db)) -> CalendarCalendarRead:
    calendar = db.get(CalendarCalendar, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=404, detail="Calendar not found")
    calendar.selected = payload.selected
    db.commit()
    db.refresh(calendar)
    return CalendarCalendarRead.model_validate(calendar, from_attributes=True)


@router.get("/api/integrations/google_calendar/events", response_model=list[CalendarEventRead])
def list_events(db: Session = Depends(get_db)) -> list[CalendarEventRead]:
    events = (
        db.query(CalendarEventCache)
        .join(CalendarCalendar)
        .filter(CalendarCalendar.selected.is_(True))
        .order_by(CalendarEventCache.start_datetime, CalendarEventCache.start_date)
        .all()
    )
    return [CalendarEventRead.model_validate(e, from_attributes=True) for e in events]


@router.get("/api/integrations/google_health/summaries", response_model=list[GoogleHealthDailySummaryRead])
def list_google_health_summaries(db: Session = Depends(get_db)) -> list[GoogleHealthDailySummaryRead]:
    rows = db.query(GoogleHealthDailySummary).order_by(GoogleHealthDailySummary.date.desc()).limit(31).all()
    return [GoogleHealthDailySummaryRead.model_validate(r, from_attributes=True) for r in rows]


@router.get("/api/integrations/google_health/sessions", response_model=list[GoogleHealthSessionRead])
def list_google_health_sessions(db: Session = Depends(get_db)) -> list[GoogleHealthSessionRead]:
    rows = db.query(GoogleHealthSession).order_by(GoogleHealthSession.end_time.desc()).limit(20).all()
    return [GoogleHealthSessionRead.model_validate(r, from_attributes=True) for r in rows]


_CATEGORY_DAILY_FIELDS = {
    "activity": (
        "steps",
        "distance_km",
        "floors",
        "active_zone_minutes",
        "active_calories_kcal",
        "calories_out",
        "vo2_max",
    ),
    "health_metrics": (
        "heart_rate_avg_bpm",
        "resting_heart_rate",
        "hrv_daily_rmssd_ms",
        "oxygen_saturation_avg_percent",
        "respiratory_rate_breaths_per_min",
        "weight_kg",
        "body_fat_percent",
        "blood_glucose_mg_dl",
    ),
    "sleep": ("sleep_minutes_asleep",),
}


@router.get("/api/integrations/google_health/metric-groups", response_model=list[GoogleHealthMetricGroupStatus])
def google_health_metric_groups(db: Session = Depends(get_db)) -> list[GoogleHealthMetricGroupStatus]:
    """Per-category (matching the registry's scope categories: activity,
    health_metrics, sleep) availability — whether *anything* useful was
    persisted recently, not a claim that every possible metric/source is
    present. Availability depends on the connected account, contributing
    devices/apps, granted scopes, and device capabilities."""
    conn = db.get(IntegrationConnection, "google_health")
    recent = db.query(GoogleHealthDailySummary).order_by(GoogleHealthDailySummary.date.desc()).limit(31).all()
    sessions = db.query(GoogleHealthSession).order_by(GoogleHealthSession.end_time.desc()).limit(31).all()

    results = []
    for category, fields_ in _CATEGORY_DAILY_FIELDS.items():
        has_data = any(getattr(row, f, None) is not None for row in recent for f in fields_)
        if category == "sleep":
            has_data = has_data or any(s.session_type == "sleep" for s in sessions)
        if category == "activity":
            has_data = has_data or any(s.session_type == "exercise" for s in sessions)
        results.append(
            GoogleHealthMetricGroupStatus(
                category=category, has_data=has_data, last_error=conn.last_error if conn else None
            )
        )
    return results


@router.get("/api/integrations/google_health/unsupported-metrics")
def google_health_unsupported_metrics() -> list[str]:
    return list(UNSUPPORTED_METRICS)
