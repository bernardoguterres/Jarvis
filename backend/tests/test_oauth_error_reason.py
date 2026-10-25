"""A token refresh failure keeps Google's OAuth error code, not only its
description, which is often just "Bad Request"."""

from __future__ import annotations

import httpx
import pytest

from app.providers import google_calendar, google_health


@pytest.mark.parametrize(
    ("module", "error_cls"),
    [(google_calendar, google_calendar.GoogleCalendarError), (google_health, google_health.GoogleHealthError)],
)
def test_refresh_failure_message_keeps_the_error_code(module, error_cls) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"})
    )
    with pytest.raises(error_cls) as exc:
        module.refresh_access_token(
            client=httpx.Client(transport=transport), client_id="c", client_secret="s", refresh_token="r"
        )
    assert "invalid_grant (Bad Request)" in str(exc.value.args) or "invalid_grant (Bad Request)" in getattr(exc.value, "summary", "")
