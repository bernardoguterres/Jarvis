"""Phase 9 (corrected, breadth-extended): read-only Google Health API
integration. Reads reconciled, consented data through Google Health —
which can originate from Fitbit, Pixel Watch, Health Connect, Google Fit,
or other sources the account has connected — not a Fitbit-specific API.

Verified live against the real, connected Google Health API (not just the
discovery document) during Phase 9 acceptance — see docs/DECISIONS.md
D64. Three distinct fetch mechanisms are used, per official operation
support, never sending every data type through the same one:

  - `dailyRollUp` (POST .../dataPoints:dailyRollUp): pre-aggregated daily
    totals for interval-summable metrics (steps, distance, floors, active
    zone minutes, active calories, total calories, heart rate). Rollups
    are reconciled-by-default (deduped across phone/watch), so no separate
    `reconcile` call is needed for these. Range limit: 14 days for
    heart-rate/total-calories, 90 days for the rest (confirmed exact
    values, not assumed).
  - `list` with no filter, page-size bounded, client-side truncated to the
    needed date range (GET .../dataPoints?pageSize=): for the "daily-*"
    precomputed singleton types (daily-resting-heart-rate,
    daily-heart-rate-variability, daily-oxygen-saturation,
    daily-respiratory-rate, daily-vo2-max) and for point-sample types
    (weight, body-fat, blood-glucose). A server-side `filter` query
    parameter exists for other list-fetched types but consistently
    returned INVALID_DATA_POINT_FILTER for every field-name variant tried
    against these specific "daily-*" types with a real connected account;
    a no-filter fetch with client-side date truncation is a safe, correct
    fallback within Phase 9's small (7-31 day) sync windows.
  - `list` with a real, live-verified `filter` (GET
    .../dataPoints?filter=...): for session types. Confirmed exact filter
    field names differ per type and were NOT interchangeable — sleep uses
    `sleep.interval.end_time` with UTC `...Z` timestamps; exercise uses
    `exercise.interval.civil_start_time` with civil (no `Z`) timestamps.

Response field names were also verified live and differ from what the
Phase 9 original implementation assumed — e.g. distance is
`distance.millimetersSum` (millimeters, not `distanceMeters`), and
`sleep` is a session type fetched via `list`, never `dailyRollUp`.

Daily Readiness Score, Sleep Score, Stress Management Score, and Cardio
Load/Target Load are not exposed by any Google Health data type — shown
as explicitly unsupported, never estimated or relabeled from another
metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://health.googleapis.com/v4"

SCOPE_ACTIVITY = "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"
SCOPE_HEALTH_METRICS = "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly"
SCOPE_SLEEP = "https://www.googleapis.com/auth/googlehealth.sleep.readonly"

READ_SCOPES = (SCOPE_ACTIVITY, SCOPE_HEALTH_METRICS, SCOPE_SLEEP)

# Metrics Bernardo might reasonably expect that are not exposed by any
# documented Google Health data type — shown as "unsupported" in the UI,
# never estimated or relabeled from another metric. These are proprietary
# Fitbit-app scores, not Google Health data types.
UNSUPPORTED_METRICS = (
    "Daily Readiness Score",
    "Sleep Score",
    "Stress Management Score",
    "Cardio Load / Target Load",
)


class GoogleHealthError(Exception):
    def __init__(self, code: str, summary: str, *, retry_after: int | None = None) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.retry_after = retry_after


@dataclass
class TokenResult:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str


# --------------------------------------------------------------------------
# Typed metric registry — the single source of truth for which Google
# Health data types Jarvis reads, which scope governs each, which REST
# operation fetches it, how it's synced locally, and its BODY-only context
# eligibility. Used by the sync service, the Integrations Centre API, and
# tests — never duplicated ad hoc elsewhere.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RollupMetricDef:
    """A metric fetched via `dailyRollUp` — one aggregated value per day."""

    key: str
    data_type: str
    scope: str
    category: str  # "activity" | "health_metrics"
    max_range_days: int
    record_kind: str = "daily_summary"
    body_only: bool = True
    extract: Callable[[dict], dict[str, Any]] = field(repr=False, compare=False, default=lambda v: {})


@dataclass(frozen=True)
class DailyListMetricDef:
    """A metric fetched via `list` (no server-side date filter — that
    filter syntax was live-verified to reject every field-name variant
    tried for these singleton/point types), bounded by page size and
    truncated client-side to the sync window."""

    key: str
    data_type: str
    scope: str
    category: str
    record_kind: str = "daily_summary"
    body_only: bool = True
    page_size: int = 90
    extract_date: Callable[[dict], date_type | None] = field(repr=False, compare=False, default=lambda p: None)
    extract: Callable[[dict], dict[str, Any]] = field(repr=False, compare=False, default=lambda p: {})


@dataclass(frozen=True)
class SessionMetricDef:
    """A metric fetched via `list` with a real, live-verified filter —
    session/event-shaped data (sleep, exercise), never collapsed into a
    single daily rollup number."""

    key: str
    data_type: str
    scope: str
    category: str
    record_kind: str = "session"
    body_only: bool = True
    page_size: int = 25
    filter_template: Callable[[date_type, date_type], str] = field(repr=False, compare=False, default=lambda s, e: "")


def _as_int(v: Any) -> int | None:
    """Several Google Health fields are declared `type: string, format:
    int64` in the discovery doc (a common protobuf-JSON convention for
    64-bit integers) and are confirmed live to arrive as JSON strings, not
    numbers — e.g. `steps.countSum: "4321"`. Cast defensively regardless of
    whether the API sends a string or a number."""
    if v is None:
        return None
    return int(v)


def _steps_extract(v: dict) -> dict:
    return {"steps": _as_int(v.get("steps", {}).get("countSum"))}


def _distance_extract(v: dict) -> dict:
    mm = _as_int(v.get("distance", {}).get("millimetersSum"))
    return {"distance_km": (mm / 1_000_000.0) if mm is not None else None}


def _floors_extract(v: dict) -> dict:
    return {"floors": _as_int(v.get("floors", {}).get("countSum"))}


def _azm_extract(v: dict) -> dict:
    azm = v.get("activeZoneMinutes", {})
    parts = [_as_int(azm.get(k)) for k in ("sumInFatBurnHeartZone", "sumInCardioHeartZone", "sumInPeakHeartZone")]
    present = [p for p in parts if p is not None]
    return {"active_zone_minutes": sum(present) if present else None}


def _active_calories_extract(v: dict) -> dict:
    return {"active_calories_kcal": v.get("activeEnergyBurned", {}).get("kcalSum")}


def _total_calories_extract(v: dict) -> dict:
    return {"calories_out": v.get("totalCalories", {}).get("kcalSum")}


def _heart_rate_extract(v: dict) -> dict:
    hr = v.get("heartRate", {})
    return {
        "heart_rate_avg_bpm": hr.get("beatsPerMinuteAvg"),
        "heart_rate_min_bpm": hr.get("beatsPerMinuteMin"),
        "heart_rate_max_bpm": hr.get("beatsPerMinuteMax"),
    }


ROLLUP_METRICS: tuple[RollupMetricDef, ...] = (
    RollupMetricDef("steps", "steps", SCOPE_ACTIVITY, "activity", 90, extract=_steps_extract),
    RollupMetricDef("distance", "distance", SCOPE_ACTIVITY, "activity", 90, extract=_distance_extract),
    RollupMetricDef("floors", "floors", SCOPE_ACTIVITY, "activity", 90, extract=_floors_extract),
    RollupMetricDef(
        "active_zone_minutes", "active-zone-minutes", SCOPE_ACTIVITY, "activity", 90, extract=_azm_extract
    ),
    RollupMetricDef(
        "active_calories", "active-energy-burned", SCOPE_ACTIVITY, "activity", 90, extract=_active_calories_extract
    ),
    RollupMetricDef(
        "total_calories", "total-calories", SCOPE_ACTIVITY, "activity", 14, extract=_total_calories_extract
    ),
    RollupMetricDef(
        "heart_rate", "heart-rate", SCOPE_HEALTH_METRICS, "health_metrics", 14, extract=_heart_rate_extract
    ),
)


def _date_from_google_date(obj: dict | None) -> date_type | None:
    if not obj:
        return None
    try:
        return date_type(obj["year"], obj["month"], obj["day"])
    except (KeyError, ValueError, TypeError):
        return None


def _daily_resting_hr_extract_date(p: dict) -> date_type | None:
    return _date_from_google_date(p.get("dailyRestingHeartRate", {}).get("date"))


def _daily_resting_hr_extract(p: dict) -> dict:
    return {"resting_heart_rate": _as_int(p.get("dailyRestingHeartRate", {}).get("beatsPerMinute"))}


def _daily_hrv_extract_date(p: dict) -> date_type | None:
    return _date_from_google_date(p.get("dailyHeartRateVariability", {}).get("date"))


def _daily_hrv_extract(p: dict) -> dict:
    v = p.get("dailyHeartRateVariability", {})
    return {"hrv_daily_rmssd_ms": v.get("averageHeartRateVariabilityMilliseconds")}


def _daily_spo2_extract_date(p: dict) -> date_type | None:
    return _date_from_google_date(p.get("dailyOxygenSaturation", {}).get("date"))


def _daily_spo2_extract(p: dict) -> dict:
    return {"oxygen_saturation_avg_percent": p.get("dailyOxygenSaturation", {}).get("averagePercentage")}


def _daily_resp_rate_extract_date(p: dict) -> date_type | None:
    return _date_from_google_date(p.get("dailyRespiratoryRate", {}).get("date"))


def _daily_resp_rate_extract(p: dict) -> dict:
    return {"respiratory_rate_breaths_per_min": p.get("dailyRespiratoryRate", {}).get("breathsPerMinute")}


def _daily_vo2max_extract_date(p: dict) -> date_type | None:
    return _date_from_google_date(p.get("dailyVo2Max", {}).get("date"))


def _daily_vo2max_extract(p: dict) -> dict:
    return {"vo2_max": p.get("dailyVo2Max", {}).get("vo2Max")}


def _civil_time_to_date(civil_time: dict | None) -> date_type | None:
    if not civil_time:
        return None
    return _date_from_google_date(civil_time.get("date"))


def _weight_extract_date(p: dict) -> date_type | None:
    return _civil_time_to_date(p.get("weight", {}).get("sampleTime", {}).get("civilTime"))


def _weight_extract(p: dict) -> dict:
    grams = p.get("weight", {}).get("weightGrams")
    source = p.get("dataSource", {}).get("platform")
    return {"weight_kg": (grams / 1000.0) if grams is not None else None, "weight_source": source}


def _body_fat_extract_date(p: dict) -> date_type | None:
    return _civil_time_to_date(p.get("bodyFat", {}).get("sampleTime", {}).get("civilTime"))


def _body_fat_extract(p: dict) -> dict:
    return {"body_fat_percent": p.get("bodyFat", {}).get("percentage")}


def _blood_glucose_extract_date(p: dict) -> date_type | None:
    return _civil_time_to_date(p.get("bloodGlucose", {}).get("sampleTime", {}).get("civilTime"))


def _blood_glucose_extract(p: dict) -> dict:
    return {"blood_glucose_mg_dl": p.get("bloodGlucose", {}).get("bloodGlucoseMilligramsPerDeciliter")}


DAILY_LIST_METRICS: tuple[DailyListMetricDef, ...] = (
    DailyListMetricDef(
        "daily_resting_heart_rate",
        "daily-resting-heart-rate",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_daily_resting_hr_extract_date,
        extract=_daily_resting_hr_extract,
    ),
    DailyListMetricDef(
        "daily_heart_rate_variability",
        "daily-heart-rate-variability",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_daily_hrv_extract_date,
        extract=_daily_hrv_extract,
    ),
    DailyListMetricDef(
        "daily_oxygen_saturation",
        "daily-oxygen-saturation",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_daily_spo2_extract_date,
        extract=_daily_spo2_extract,
    ),
    DailyListMetricDef(
        "daily_respiratory_rate",
        "daily-respiratory-rate",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_daily_resp_rate_extract_date,
        extract=_daily_resp_rate_extract,
    ),
    DailyListMetricDef(
        "daily_vo2_max",
        "daily-vo2-max",
        SCOPE_ACTIVITY,
        "activity",
        extract_date=_daily_vo2max_extract_date,
        extract=_daily_vo2max_extract,
    ),
    DailyListMetricDef(
        "weight",
        "weight",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_weight_extract_date,
        extract=_weight_extract,
    ),
    DailyListMetricDef(
        "body_fat",
        "body-fat",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_body_fat_extract_date,
        extract=_body_fat_extract,
    ),
    DailyListMetricDef(
        "blood_glucose",
        "blood-glucose",
        SCOPE_HEALTH_METRICS,
        "health_metrics",
        extract_date=_blood_glucose_extract_date,
        extract=_blood_glucose_extract,
    ),
)


def _sleep_filter(start_date: date_type, end_date: date_type) -> str:
    # Live-verified: sleep is filtered by *end* time, in UTC with a "Z"
    # suffix — NOT civil time, unlike exercise below.
    start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
    return (
        f'sleep.interval.end_time >= "{start.strftime("%Y-%m-%dT%H:%M:%SZ")}" AND '
        f'sleep.interval.end_time < "{end.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    )


def _exercise_filter(start_date: date_type, end_date: date_type) -> str:
    # Live-verified: exercise is filtered by *civil* start time (no "Z") —
    # the opposite convention from sleep above. Confirmed by direct testing
    # against the real API, not assumed from the discovery document alone.
    return (
        f'exercise.interval.civil_start_time >= "{start_date.isoformat()}T00:00:00" AND '
        f'exercise.interval.civil_start_time < "{end_date.isoformat()}T00:00:00"'
    )


SESSION_METRICS: tuple[SessionMetricDef, ...] = (
    SessionMetricDef("sleep", "sleep", SCOPE_SLEEP, "sleep", filter_template=_sleep_filter),
    SessionMetricDef("exercise", "exercise", SCOPE_ACTIVITY, "activity", filter_template=_exercise_filter),
)


@dataclass
class SessionRecord:
    session_type: str
    external_id: str
    start_time: datetime
    end_time: datetime
    activity_type: str | None = None
    calories_kcal: float | None = None
    distance_km: float | None = None
    average_heart_rate_bpm: int | None = None
    minutes_asleep: int | None = None
    minutes_awake: int | None = None
    stages: list[dict] = field(default_factory=list)
    source_platform: str | None = None
    source_device: str | None = None


@dataclass
class DailySummary:
    date: date_type
    steps: int | None = None
    distance_km: float | None = None
    floors: int | None = None
    active_zone_minutes: int | None = None
    active_calories_kcal: float | None = None
    calories_out: float | None = None
    heart_rate_avg_bpm: int | None = None
    heart_rate_min_bpm: int | None = None
    heart_rate_max_bpm: int | None = None
    resting_heart_rate: int | None = None
    hrv_daily_rmssd_ms: float | None = None
    oxygen_saturation_avg_percent: float | None = None
    respiratory_rate_breaths_per_min: float | None = None
    vo2_max: float | None = None
    weight_kg: float | None = None
    weight_source: str | None = None
    body_fat_percent: float | None = None
    blood_glucose_mg_dl: float | None = None
    sleep_duration_ms: int | None = None
    sleep_minutes_asleep: int | None = None
    sleep_efficiency: int | None = None
    sleep_type: str | None = None
    source_platforms: set[str] = field(default_factory=set)


@dataclass
class HealthSyncResult:
    summaries: dict[date_type, DailySummary]
    sessions: list[SessionRecord]
    # metric key -> error summary, for metrics that failed without aborting
    # the rest of the sync (partial availability is normal, not fatal).
    partial_failures: dict[str, str] = field(default_factory=dict)


def build_authorization_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    # No `include_granted_scopes` here, deliberately: Google Health requests
    # a fixed set of three read-only scopes and never uses incremental
    # authorization (unlike Google Calendar, which adds a write scope
    # later). Live Phase 9 acceptance found that this flag causes Google to
    # return the union of every scope ever granted to the Cloud project for
    # this user — not just this client — so a Health token ended up also
    # carrying Calendar's scopes. Omitting the parameter (never `"false"`)
    # is the provider-correct way to request only what's asked for here.
    # See docs/DECISIONS.md D63.
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(READ_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
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
        raise GoogleHealthError("token_exchange_failed", f"HTTP {response.status_code} from token endpoint")
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
        # See google_calendar.py's identical fix — Google's OAuth error
        # body is a standard, non-secret {"error", "error_description"}
        # pair, never a credential value.
        try:
            error_body = response.json()
            reason = error_body.get("error_description") or error_body.get("error") or "unknown"
        except ValueError:
            reason = "unparseable response body"
        raise GoogleHealthError(
            "token_refresh_failed", f"HTTP {response.status_code} from token endpoint: {reason}"
        )
    body = response.json()
    return TokenResult(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in", 3600),
        scope=body.get("scope", ""),
    )


def revoke_token(*, client: httpx.Client, token: str) -> bool:
    response = client.post(REVOKE_ENDPOINT, data={"token": token})
    return response.status_code == 200


def _civil_date(d: date_type) -> dict:
    """CivilDateTime per the real API's discovery doc: {date: {year, month,
    day}, time?: TimeOfDay} — NOT a plain ISO date/datetime string. Omitting
    `time` defaults to midnight, which is what a daily rollup boundary needs."""
    return {"date": {"year": d.year, "month": d.month, "day": d.day}}


def _daily_roll_up(
    client: httpx.Client, access_token: str, data_type: str, start_date: date_type, end_date: date_type, max_range_days: int
) -> list[dict]:
    """Calls dailyRollUp for one data type over [start_date, end_date)
    (exclusive end, per the API's CivilTimeInterval contract), following
    pagination until exhausted. Returns the raw rollupDataPoints list."""
    if (end_date - start_date).days > max_range_days:
        raise GoogleHealthError(
            "range_too_large",
            f"{data_type} dailyRollUp range exceeds the {max_range_days}-day limit for this data type.",
        )

    points: list[dict] = []
    page_token: str | None = None
    while True:
        body: dict = {
            "range": {"start": _civil_date(start_date), "end": _civil_date(end_date)},
            "windowSizeDays": 1,
        }
        if page_token:
            body["pageToken"] = page_token

        response = client.post(
            f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp",
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
        if response.status_code == 404:
            return points  # no data for this type/range — not an error
        _raise_for_status(response, context=f"dailyRollUp:{data_type}")

        payload = response.json()
        points.extend(payload.get("rollupDataPoints", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return points


def _chunk_date_range(start_date: date_type, end_date: date_type, max_days: int) -> list[tuple[date_type, date_type]]:
    """Splits [start_date, end_date) into consecutive, non-overlapping,
    gap-free chunks of at most `max_days` civil days each (the last chunk
    may be shorter). Each chunk's end is the next chunk's start, so every
    day in the requested range is covered by exactly one chunk — never
    duplicated, never skipped."""
    chunks: list[tuple[date_type, date_type]] = []
    cursor = start_date
    while cursor < end_date:
        chunk_end = min(cursor + timedelta(days=max_days), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def _daily_roll_up_chunked(
    client: httpx.Client, access_token: str, data_type: str, start_date: date_type, end_date: date_type, max_range_days: int
) -> tuple[list[dict], list[str]]:
    """Fetches a metric across a range that may exceed its per-request
    range limit by issuing sequential, non-overlapping `dailyRollUp` calls
    of at most `max_range_days` each and combining the results. A failure
    in one chunk is recorded and does not discard points already fetched
    from other, successful chunks for this same metric — no immediate
    retry is attempted. Never called with overlapping chunks, so no
    deduplication step is needed: each day is fetched by exactly one
    chunk."""
    points: list[dict] = []
    errors: list[str] = []
    for chunk_start, chunk_end in _chunk_date_range(start_date, end_date, max_range_days):
        try:
            points.extend(_daily_roll_up(client, access_token, data_type, chunk_start, chunk_end, max_range_days))
        except GoogleHealthError as exc:
            errors.append(f"{chunk_start.isoformat()}..{chunk_end.isoformat()}: {exc.summary}")
    return points, errors


def _list_unfiltered(client: httpx.Client, access_token: str, data_type: str, page_size: int) -> list[dict]:
    """Fetches recent data points for a type with no server-side date
    filter (that filter syntax was live-verified to reject every field-name
    variant tried for these types), following pagination up to `page_size`
    total points. Bounded and safe for Phase 9's small sync windows."""
    points: list[dict] = []
    page_token: str | None = None
    while len(points) < page_size:
        params: dict[str, Any] = {"pageSize": min(page_size, 100)}
        if page_token:
            params["pageToken"] = page_token
        response = client.get(
            f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        if response.status_code == 404:
            return points
        _raise_for_status(response, context=f"list:{data_type}")
        payload = response.json()
        points.extend(payload.get("dataPoints", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return points


def _list_filtered(
    client: httpx.Client, access_token: str, data_type: str, filter_expr: str, page_size: int
) -> list[dict]:
    points: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"filter": filter_expr, "pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        response = client.get(
            f"{API_BASE}/users/me/dataTypes/{data_type}/dataPoints",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
        )
        if response.status_code == 404:
            return points
        _raise_for_status(response, context=f"list:{data_type}")
        payload = response.json()
        points.extend(payload.get("dataPoints", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return points


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_sleep_session(point: dict) -> SessionRecord | None:
    sleep = point.get("sleep", {})
    interval = sleep.get("interval", {})
    start = _parse_utc(interval.get("startTime"))
    end = _parse_utc(interval.get("endTime"))
    if start is None or end is None:
        return None
    stages = sleep.get("stages", [])
    awake_seconds = 0.0
    for stage in stages:
        if stage.get("type") == "AWAKE":
            s = _parse_utc(stage.get("startTime"))
            e = _parse_utc(stage.get("endTime"))
            if s and e:
                awake_seconds += (e - s).total_seconds()
    total_seconds = (end - start).total_seconds()
    asleep_minutes = int(round(max(total_seconds - awake_seconds, 0) / 60))
    awake_minutes = int(round(awake_seconds / 60))
    data_source = point.get("dataSource", {})
    return SessionRecord(
        session_type="sleep",
        external_id=point.get("name", f"sleep:{interval.get('startTime')}:{interval.get('endTime')}"),
        start_time=start,
        end_time=end,
        activity_type=sleep.get("type"),
        minutes_asleep=asleep_minutes,
        minutes_awake=awake_minutes,
        stages=[{"type": s.get("type"), "start": s.get("startTime"), "end": s.get("endTime")} for s in stages],
        source_platform=data_source.get("platform"),
        source_device=data_source.get("device", {}).get("displayName"),
    )


def _parse_exercise_session(point: dict) -> SessionRecord | None:
    exercise = point.get("exercise", {})
    interval = exercise.get("interval", {})
    start = _parse_utc(interval.get("startTime"))
    end = _parse_utc(interval.get("endTime"))
    if start is None or end is None:
        return None
    metrics = exercise.get("metricsSummary", {})
    distance_mm = metrics.get("distanceMillimeters")
    avg_hr = metrics.get("averageHeartRateBeatsPerMinute")
    data_source = point.get("dataSource", {})
    return SessionRecord(
        session_type="exercise",
        external_id=point.get("name", f"exercise:{interval.get('startTime')}:{interval.get('endTime')}"),
        start_time=start,
        end_time=end,
        activity_type=exercise.get("displayName") or exercise.get("exerciseType"),
        calories_kcal=metrics.get("caloriesKcal"),
        distance_km=(float(distance_mm) / 1_000_000.0) if distance_mm is not None else None,
        average_heart_rate_bpm=int(avg_hr) if avg_hr is not None else None,
        source_platform=data_source.get("platform"),
        source_device=data_source.get("device", {}).get("displayName"),
    )


_SESSION_PARSERS: dict[str, Callable[[dict], SessionRecord | None]] = {
    "sleep": _parse_sleep_session,
    "exercise": _parse_exercise_session,
}


def fetch_health_data(
    *, client: httpx.Client, access_token: str, start_date: date_type, end_date: date_type
) -> HealthSyncResult:
    """Fetches and normalizes Google Health data for [start_date, end_date)
    across all registered metrics. A failure fetching one metric is
    recorded in `partial_failures` and does not abort the rest of the
    sync — missing/unsupported data for a given account is normal."""
    summaries: dict[date_type, DailySummary] = {}
    sessions: list[SessionRecord] = []
    partial_failures: dict[str, str] = {}

    def _get_or_create(day: date_type) -> DailySummary:
        if day not in summaries:
            summaries[day] = DailySummary(date=day)
        return summaries[day]

    def _parse_day(point: dict) -> date_type | None:
        # civilStartTime is a structured CivilDateTime object
        # ({date: {year, month, day}, time: {}}), NOT a plain ISO string —
        # confirmed live against the real API (docs/DECISIONS.md D64).
        return _date_from_google_date(point.get("civilStartTime", {}).get("date"))

    for metric in ROLLUP_METRICS:
        points, chunk_errors = _daily_roll_up_chunked(
            client, access_token, metric.data_type, start_date, end_date, metric.max_range_days
        )
        if chunk_errors:
            partial_failures[metric.key] = "; ".join(chunk_errors)
        for point in points:
            day = _parse_day(point)
            if day is None:
                continue
            # The metric's value sits directly on the rollup point (keyed
            # by the data type's camelCase field name, e.g. `point["steps"]`
            # `.countSum`) — there is no `"value"` wrapper, contrary to the
            # original (unverified) assumption. Confirmed live (D64).
            #
            # `extract()` indexes into an external, untrusted response
            # shape — a single point that doesn't match the expected shape
            # (a genuinely novel API variant, a transient malformed
            # response) must only cost this one metric, never crash the
            # whole sync and silently discard every other metric's already-
            # successfully-parsed data. See docs/DECISIONS.md D83.
            try:
                values = metric.extract(point)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                partial_failures[metric.key] = f"Malformed data point: {exc}"
                continue
            summary = _get_or_create(day)
            for field_name, val in values.items():
                if val is not None:
                    setattr(summary, field_name, val)

    for metric in DAILY_LIST_METRICS:
        try:
            points = _list_unfiltered(client, access_token, metric.data_type, page_size=max(90, (end_date - start_date).days + 10))
        except GoogleHealthError as exc:
            partial_failures[metric.key] = exc.summary
            continue
        for point in points:
            try:
                day = metric.extract_date(point)
                if day is None or day < start_date or day >= end_date:
                    continue
                values = metric.extract(point)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                partial_failures[metric.key] = f"Malformed data point: {exc}"
                continue
            summary = _get_or_create(day)
            for field_name, val in values.items():
                if val is not None and getattr(summary, field_name, None) is None:
                    setattr(summary, field_name, val)
            platform = point.get("dataSource", {}).get("platform")
            if platform:
                summary.source_platforms.add(platform)

    for metric in SESSION_METRICS:
        parser = _SESSION_PARSERS[metric.key]
        try:
            filter_expr = metric.filter_template(start_date, end_date)
            points = _list_filtered(client, access_token, metric.data_type, filter_expr, metric.page_size)
        except GoogleHealthError as exc:
            partial_failures[metric.key] = exc.summary
            continue
        for point in points:
            try:
                record = parser(point)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
                partial_failures[metric.key] = f"Malformed data point: {exc}"
                continue
            if record is not None:
                sessions.append(record)
                if record.source_platform:
                    _get_or_create(record.end_time.date()).source_platforms.add(record.source_platform)

    # Fold each night's sleep session into that night's daily summary as a
    # compact rollup (dashboard/context use) — the full stage detail stays
    # in the session record, never duplicated into the daily summary.
    for record in sessions:
        if record.session_type != "sleep":
            continue
        day = record.end_time.date()
        summary = _get_or_create(day)
        total_minutes = (record.minutes_asleep or 0) + (record.minutes_awake or 0)
        summary.sleep_duration_ms = int((record.end_time - record.start_time).total_seconds() * 1000)
        summary.sleep_minutes_asleep = record.minutes_asleep
        summary.sleep_efficiency = (
            int(round(100 * record.minutes_asleep / total_minutes)) if total_minutes and record.minutes_asleep is not None else None
        )
        summary.sleep_type = record.activity_type

    return HealthSyncResult(summaries=summaries, sessions=sessions, partial_failures=partial_failures)


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    if response.status_code == 401:
        raise GoogleHealthError("unauthorized", f"Google Health returned 401 for {context} — token may be expired/revoked")
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "3600"))
        raise GoogleHealthError("rate_limited", f"Google Health rate limit hit for {context}", retry_after=retry_after)
    if response.status_code >= 500:
        raise GoogleHealthError(f"http_{response.status_code}", f"Google Health server error for {context}")
    if response.status_code >= 400:
        raise GoogleHealthError(f"http_{response.status_code}", f"Google Health API error {response.status_code} for {context}")
