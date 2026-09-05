"""Google Health API provider — a general Google Health integration (not
Fitbit-specific; data can come from Fitbit, Pixel Watch, Health Connect,
Google Fit, or other connected sources). Every request is mocked via
httpx.MockTransport; no real network call is ever made.

Field names and filter syntax below were verified live against the real,
connected Google Health API during Phase 9 acceptance (see
docs/DECISIONS.md D64) — e.g. distance is millimeters (not meters), sleep
is a session type fetched via `list` (never `dailyRollUp`), and sleep vs.
exercise use different filter field conventions (end_time/UTC vs.
civil_start_time/civil)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.providers import google_health


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_no_request_ever_targets_legacy_fitbit_api() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host)
        assert "fitbit.com" not in request.url.host
        if "dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": []})
        return httpx.Response(200, json={"dataPoints": []})

    google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 3)
    )
    assert seen_hosts
    assert all(host == "health.googleapis.com" for host in seen_hosts)


def test_read_only_scopes_only_no_write_scope_ever_requested() -> None:
    url = google_health.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/api/integrations/google_health/oauth/callback", state="s", code_challenge="c"
    )
    query = httpx.QueryParams(httpx.URL(url).query.decode())
    requested_scopes = query["scope"].split(" ")
    for scope in requested_scopes:
        assert scope.endswith(".readonly"), f"non-readonly scope requested: {scope}"
    assert set(requested_scopes) == set(google_health.READ_SCOPES)
    assert "location" not in query["scope"]
    assert "nutrition" not in query["scope"]


def test_google_health_requests_exactly_its_three_read_only_scopes() -> None:
    url = google_health.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/api/integrations/google_health/oauth/callback", state="s", code_challenge="c"
    )
    query = httpx.QueryParams(httpx.URL(url).query.decode())
    requested_scopes = set(query["scope"].split(" "))
    assert requested_scopes == {
        "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
        "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
        "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    }


def test_google_health_authorization_omits_include_granted_scopes() -> None:
    """Google Health has a fixed scope set and never uses incremental
    authorization (unlike Calendar, which adds a write scope later). Live
    Phase 9 acceptance found that requesting `include_granted_scopes=true`
    here caused Google to return the union of every scope ever granted to
    the Cloud project for this user, not just this client — so a Health
    token ended up also carrying Calendar's scopes (docs/DECISIONS.md D63).
    The parameter must be omitted entirely, never sent as "false"."""
    url = google_health.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/api/integrations/google_health/oauth/callback", state="s", code_challenge="c"
    )
    assert "include_granted_scopes" not in url


def test_redirect_uri_matches_google_health_callback() -> None:
    url = google_health.build_authorization_url(
        client_id="cid", redirect_uri="http://127.0.0.1:8000/api/integrations/google_health/oauth/callback", state="s", code_challenge="c"
    )
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fapi%2Fintegrations%2Fgoogle_health%2Foauth%2Fcallback" in url


def _empty_handler(request: httpx.Request) -> httpx.Response:
    if "dataPoints:dailyRollUp" in request.url.path:
        return httpx.Response(200, json={"rollupDataPoints": []})
    return httpx.Response(200, json={"dataPoints": []})


def _rollup_point(year: int, month: int, day: int, **fields: dict) -> dict:
    """Matches the real dailyRollUp response shape, confirmed live: a
    structured `civilStartTime` CivilDateTime object (not a plain string),
    and the metric's value sitting directly on the point — no `"value"`
    wrapper (docs/DECISIONS.md D64)."""
    return {"civilStartTime": {"date": {"year": year, "month": month, "day": day}}, **fields}


def test_steps_and_distance_use_the_real_rollup_field_names() -> None:
    """distance is millimeters (distanceMillimetersSum-style field
    `distance.millimetersSum`), not the old (wrong) assumption of meters —
    a real bug found and fixed live (docs/DECISIONS.md D64)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(
                200, json={"rollupDataPoints": [_rollup_point(2026, 8, 1, steps={"countSum": "4321"})]}
            )
        if "dataTypes/distance/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(
                200, json={"rollupDataPoints": [_rollup_point(2026, 8, 1, distance={"millimetersSum": "5000000"})]}
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2)
    )
    summary = result.summaries[date(2026, 8, 1)]
    assert summary.steps == 4321
    assert summary.distance_km == 5.0
    # Never fabricated: fields with no data stay None.
    assert summary.weight_kg is None


def test_heart_rate_rollup_extracts_avg_min_max() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/heart-rate/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "rollupDataPoints": [
                        _rollup_point(
                            2026, 8, 1, heartRate={"beatsPerMinuteAvg": 70, "beatsPerMinuteMin": 50, "beatsPerMinuteMax": 140}
                        )
                    ]
                },
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2)
    )
    summary = result.summaries[date(2026, 8, 1)]
    assert (summary.heart_rate_avg_bpm, summary.heart_rate_min_bpm, summary.heart_rate_max_bpm) == (70, 50, 140)


def test_daily_list_metric_truncates_to_requested_range_client_side() -> None:
    """The 'daily-*' precomputed types are fetched via `list` with no
    server-side date filter (that filter syntax was live-verified to
    reject every field-name variant tried), so results outside the
    requested [start, end) window must be truncated client-side."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/daily-resting-heart-rate/dataPoints" in request.url.path and "dailyRollUp" not in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dataPoints": [
                        {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 8, "day": 1}, "beatsPerMinute": "55"}},
                        {"dailyRestingHeartRate": {"date": {"year": 2026, "month": 7, "day": 15}, "beatsPerMinute": "60"}},
                    ]
                },
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2)
    )
    assert result.summaries[date(2026, 8, 1)].resting_heart_rate == 55
    assert date(2026, 7, 15) not in result.summaries


def test_weight_extracts_grams_to_kg_and_source_platform() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/weight/dataPoints" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dataPoints": [
                        {
                            "dataSource": {"platform": "FITBIT"},
                            "weight": {"weightGrams": 70000, "sampleTime": {"civilTime": {"date": {"year": 2026, "month": 8, "day": 1}}}},
                        }
                    ]
                },
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2)
    )
    summary = result.summaries[date(2026, 8, 1)]
    assert summary.weight_kg == 70.0
    assert summary.weight_source == "FITBIT"
    assert "FITBIT" in summary.source_platforms


def test_sleep_session_parses_stages_into_minutes_asleep_and_awake() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/sleep/dataPoints" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dataPoints": [
                        {
                            "name": "users/me/dataTypes/sleep/dataPoints/abc",
                            "dataSource": {"platform": "FITBIT", "device": {"displayName": "Google Fitbit Air"}},
                            "sleep": {
                                "interval": {"startTime": "2026-08-25T22:00:00Z", "endTime": "2026-08-26T06:00:00Z"},
                                "type": "STAGES",
                                "stages": [
                                    {"type": "LIGHT", "startTime": "2026-08-25T22:00:00Z", "endTime": "2026-08-26T05:00:00Z"},
                                    {"type": "AWAKE", "startTime": "2026-08-26T05:00:00Z", "endTime": "2026-08-26T05:30:00Z"},
                                    {"type": "REM", "startTime": "2026-08-26T05:30:00Z", "endTime": "2026-08-26T06:00:00Z"},
                                ],
                            },
                        }
                    ]
                },
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 25), end_date=date(2026, 8, 27)
    )
    assert len(result.sessions) == 1
    session = result.sessions[0]
    assert session.session_type == "sleep"
    assert session.minutes_awake == 30
    assert session.minutes_asleep == 8 * 60 - 30
    assert session.source_platform == "FITBIT"
    # Folded into that night's (end-date) daily summary as a compact rollup.
    summary = result.summaries[date(2026, 8, 26)]
    assert summary.sleep_minutes_asleep == session.minutes_asleep
    assert summary.sleep_type == "STAGES"


def test_exercise_session_parses_metrics_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/exercise/dataPoints" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "dataPoints": [
                        {
                            "name": "users/me/dataTypes/exercise/dataPoints/def",
                            "dataSource": {"platform": "FITBIT", "device": {"displayName": "Google Fitbit Air"}},
                            "exercise": {
                                "interval": {"startTime": "2026-08-25T15:34:47Z", "endTime": "2026-08-25T15:55:16Z"},
                                "displayName": "Sport",
                                "metricsSummary": {
                                    "caloriesKcal": 138,
                                    "distanceMillimeters": 907200,
                                    "averageHeartRateBeatsPerMinute": "142",
                                },
                            },
                        }
                    ]
                },
            )
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 25), end_date=date(2026, 8, 27)
    )
    assert len(result.sessions) == 1
    session = result.sessions[0]
    assert session.session_type == "exercise"
    assert session.activity_type == "Sport"
    assert session.calories_kcal == 138
    assert round(session.distance_km, 4) == 0.9072
    assert session.average_heart_rate_bpm == 142


def test_one_metric_failure_does_not_abort_the_rest_of_the_sync() -> None:
    """Missing/unsupported data for a given account is normal — a failure
    fetching one metric must not prevent other metrics from being fetched
    and persisted."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "dataTypes/steps/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(500)
        if "dataTypes/floors/dataPoints:dailyRollUp" in request.url.path:
            return httpx.Response(200, json={"rollupDataPoints": [_rollup_point(2026, 8, 1, floors={"countSum": "5"})]})
        return _empty_handler(request)

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 2)
    )
    assert "steps" in result.partial_failures
    assert result.summaries[date(2026, 8, 1)].floors == 5


def test_heart_rate_range_over_14_days_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never reach the network — range check is client-side")

    with pytest.raises(google_health.GoogleHealthError, match="range_too_large|14-day"):
        google_health._daily_roll_up(_client(handler), "AT1", "heart-rate", date(2026, 8, 1), date(2026, 8, 20), 14)


def test_non_heart_rate_range_allows_up_to_90_days() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rollupDataPoints": []})

    # Must not raise.
    google_health._daily_roll_up(_client(handler), "AT1", "steps", date(2026, 1, 1), date(2026, 3, 1), 90)


def test_chunk_date_range_splits_31_days_into_correct_14_day_chunks() -> None:
    chunks = google_health._chunk_date_range(date(2026, 8, 1), date(2026, 9, 1), 14)
    assert chunks == [
        (date(2026, 8, 1), date(2026, 8, 15)),
        (date(2026, 8, 15), date(2026, 8, 29)),
        (date(2026, 8, 29), date(2026, 9, 1)),
    ]
    # No gaps, no overlaps: each chunk's end is exactly the next chunk's start.
    for (_, end_a), (start_b, _) in zip(chunks, chunks[1:]):
        assert end_a == start_b
    assert chunks[0][0] == date(2026, 8, 1)
    assert chunks[-1][1] == date(2026, 9, 1)
    # No chunk exceeds the limit.
    assert all((end - start).days <= 14 for start, end in chunks)


def test_chunk_date_range_does_not_split_when_within_limit() -> None:
    assert google_health._chunk_date_range(date(2026, 8, 1), date(2026, 8, 10), 14) == [
        (date(2026, 8, 1), date(2026, 8, 10))
    ]
    assert google_health._chunk_date_range(date(2026, 8, 1), date(2026, 8, 10), 90) == [
        (date(2026, 8, 1), date(2026, 8, 10))
    ]


def test_heart_rate_31_day_sync_no_longer_reports_range_too_large() -> None:
    """The real bug this corrects: a 31-day sync request for a 14-day-limited
    metric (heart-rate, total-calories) used to fail that metric outright
    with `range_too_large`. It must now transparently chunk the request and
    return real data for the full range instead."""
    seen_ranges: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if "dataTypes/heart-rate/dataPoints:dailyRollUp" not in request.url.path:
            return _empty_handler(request)
        body = json.loads(request.content)
        start = body["range"]["start"]["date"]
        end = body["range"]["end"]["date"]
        seen_ranges.append((f"{start['year']}-{start['month']:02d}-{start['day']:02d}", f"{end['year']}-{end['month']:02d}-{end['day']:02d}"))
        day = date(start["year"], start["month"], start["day"])
        return httpx.Response(
            200,
            json={
                "rollupDataPoints": [
                    {"civilStartTime": {"date": {"year": day.year, "month": day.month, "day": day.day}}, "heartRate": {"beatsPerMinuteAvg": 60}}
                ]
            },
        )

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 9, 1)
    )
    assert "heart_rate" not in result.partial_failures
    # 3 chunks were actually issued for the 14-day-limited metric.
    assert len(seen_ranges) == 3
    assert result.summaries[date(2026, 8, 1)].heart_rate_avg_bpm == 60


def test_one_chunk_failure_preserves_data_from_other_successful_chunks() -> None:
    """A failure in one chunk must be recorded against that metric without
    destroying successful data already fetched from other chunks of the
    same metric — and no immediate retry is attempted (the handler is only
    ever called once per chunk)."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if "dataTypes/heart-rate/dataPoints:dailyRollUp" not in request.url.path:
            return _empty_handler(request)
        call_count["n"] += 1
        body = json.loads(request.content)
        start = body["range"]["start"]["date"]
        if start["day"] == 1:
            return httpx.Response(500)
        day = date(start["year"], start["month"], start["day"])
        return httpx.Response(
            200,
            json={
                "rollupDataPoints": [
                    {"civilStartTime": {"date": {"year": day.year, "month": day.month, "day": day.day}}, "heartRate": {"beatsPerMinuteAvg": 60}}
                ]
            },
        )

    result = google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 9, 1)
    )
    assert "heart_rate" in result.partial_failures
    assert "2026-08-01" in result.partial_failures["heart_rate"]
    # Data from the other (successful) chunks is preserved, not discarded.
    assert date(2026, 8, 15) in result.summaries
    assert result.summaries[date(2026, 8, 15)].heart_rate_avg_bpm == 60
    # Exactly one call per chunk — no immediate retry after the failure.
    assert call_count["n"] == 3


def test_chunked_fetch_produces_no_duplicate_days() -> None:
    """Non-overlapping chunks must never cause the same civil day to be
    counted twice — each day appears in exactly one chunk's response."""
    seen_days: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if "dataTypes/heart-rate/dataPoints:dailyRollUp" not in request.url.path:
            return _empty_handler(request)
        body = json.loads(request.content)
        start_d = body["range"]["start"]["date"]
        end_d = body["range"]["end"]["date"]
        start = date(start_d["year"], start_d["month"], start_d["day"])
        end = date(end_d["year"], end_d["month"], end_d["day"])
        points = []
        cur = start
        while cur < end:
            seen_days.append(cur.isoformat())
            points.append({"civilStartTime": {"date": {"year": cur.year, "month": cur.month, "day": cur.day}}, "heartRate": {"beatsPerMinuteAvg": 60}})
            cur += google_health.timedelta(days=1)
        return httpx.Response(200, json={"rollupDataPoints": points})

    google_health.fetch_health_data(
        client=_client(handler), access_token="AT1", start_date=date(2026, 8, 1), end_date=date(2026, 9, 1)
    )
    assert len(seen_days) == len(set(seen_days)), "a civil day was requested more than once across chunks"


def test_civil_time_range_uses_the_real_civil_date_time_shape() -> None:
    """CivilDateTime is `{date: {year, month, day}, time?}`, NOT a plain ISO
    date/datetime string — confirmed against the real, live Google Health
    API, which rejects a plain-string range with HTTP 400 (D62)."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"rollupDataPoints": []})

    google_health._daily_roll_up(_client(handler), "AT1", "steps", date(2026, 8, 1), date(2026, 8, 5), 90)
    assert captured["body"]["range"]["start"] == {"date": {"year": 2026, "month": 8, "day": 1}}
    assert captured["body"]["range"]["end"] == {"date": {"year": 2026, "month": 8, "day": 5}}


def test_sleep_filter_uses_utc_end_time_exercise_filter_uses_civil_start_time() -> None:
    """Live-verified: sleep and exercise use different filter conventions
    for the same kind of range (end_time/UTC vs. civil_start_time/civil) —
    not interchangeable, confirmed by direct testing against the real API."""
    sleep_filter = google_health._sleep_filter(date(2026, 8, 1), date(2026, 8, 27))
    assert "sleep.interval.end_time" in sleep_filter
    assert sleep_filter.count("Z") >= 2

    exercise_filter = google_health._exercise_filter(date(2026, 8, 1), date(2026, 8, 27))
    assert "exercise.interval.civil_start_time" in exercise_filter
    assert "Z" not in exercise_filter


def test_401_raises_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(google_health.GoogleHealthError) as exc_info:
        google_health._daily_roll_up(_client(handler), "AT1", "steps", date(2026, 8, 1), date(2026, 8, 2), 90)
    assert exc_info.value.code == "unauthorized"


def test_429_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"})

    with pytest.raises(google_health.GoogleHealthError) as exc_info:
        google_health._daily_roll_up(_client(handler), "AT1", "steps", date(2026, 8, 1), date(2026, 8, 2), 90)
    assert exc_info.value.code == "rate_limited"
    assert exc_info.value.retry_after == 120


def test_404_treated_as_no_data_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    points = google_health._daily_roll_up(_client(handler), "AT1", "weight", date(2026, 8, 1), date(2026, 8, 2), 90)
    assert points == []


def test_unsupported_metrics_never_fabricated() -> None:
    assert "Daily Readiness Score" in google_health.UNSUPPORTED_METRICS
    assert "Sleep Score" in google_health.UNSUPPORTED_METRICS
    assert "Stress Management Score" in google_health.UNSUPPORTED_METRICS
    assert "Cardio Load / Target Load" in google_health.UNSUPPORTED_METRICS


def test_token_refresh_uses_oauth2_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://oauth2.googleapis.com/token"
        return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600, "scope": "s"})

    result = google_health.refresh_access_token(client=_client(handler), client_id="cid", client_secret="csecret", refresh_token="RT1")
    assert result.access_token == "NEW"


def test_revoke_uses_oauth2_revoke_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://oauth2.googleapis.com/revoke"
        return httpx.Response(200)

    assert google_health.revoke_token(client=_client(handler), token="AT1") is True
