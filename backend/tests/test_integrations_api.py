from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from app import integration_service


def test_connect_without_configuration_returns_409(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.post("/api/integrations/google_calendar/connect", json={"include_write_scope": False})
    assert resp.status_code == 409


def test_connect_returns_authorization_url_once_configured(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")
    resp = client_with_fake_integrations.post("/api/integrations/google_calendar/connect", json={"include_write_scope": False})
    assert resp.status_code == 200
    assert "accounts.google.com" in resp.json()["authorization_url"]


def test_connect_opens_the_system_browser_server_side_with_the_exact_authorization_url(
    client_with_fake_integrations: TestClient, fake_credential_store, monkeypatch
) -> None:
    """The native app's own "Connect" button was found to silently do
    nothing: Tauri's JS/IPC bridge is never actually present on this app's
    real content (it loads from the same plain http://127.0.0.1 origin as
    everything else, not Tauri's own trusted origin). The fix moved the
    system-browser open here, server-side — this is the regression test
    for that fix. `_no_real_browser_open` (conftest.py, autouse) already
    prevents a real browser from opening for every other test; this test
    overrides it locally to inspect exactly what would have been opened."""
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")
    calls: list[str] = []
    # Overrides conftest.py's own autouse no-op for this one test, to
    # inspect exactly what URL would have been opened.
    monkeypatch.setattr("app.routers.integrations._open_in_system_browser", calls.append)

    resp = client_with_fake_integrations.post("/api/integrations/google_calendar/connect", json={"include_write_scope": False})

    assert resp.status_code == 200
    authorization_url = resp.json()["authorization_url"]
    assert calls == [authorization_url]


def test_open_in_system_browser_swallows_a_failed_spawn(monkeypatch) -> None:
    """A machine with no `open` binary (or any other OSError spawning it)
    must never break the connect flow — the authorization_url is still
    valid and usable (e.g. copied manually), so this is a best-effort
    convenience. A unit test of `_open_in_system_browser` directly (rather
    than through the full HTTP endpoint) since conftest.py's own autouse
    fixture already replaces this exact function with a no-op for every
    other test, which a real-function-through-HTTP test would have to
    fight rather than build on."""
    from app.routers.integrations import _open_in_system_browser

    def _raise(*args, **kwargs):
        raise OSError("no such file or directory: open")

    monkeypatch.setattr("app.routers.integrations.subprocess.Popen", _raise)

    _open_in_system_browser("https://accounts.google.com/o/oauth2/v2/auth?client_id=x")  # must not raise


def test_callback_with_missing_code_shows_friendly_page(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.get("/api/integrations/google_calendar/oauth/callback")
    assert resp.status_code == 200
    assert "cancelled" in resp.text.lower()


def test_callback_error_query_param_is_html_escaped_not_injected(client_with_fake_integrations: TestClient) -> None:
    """The callback page interpolates Google's `error` query parameter
    (and, elsewhere, `str(exc)`) directly into an HTML string — added
    during the Phase 6 visual pass along with html.escape(), since this
    page is served straight to the browser that just followed the OAuth
    redirect and previously had no regression coverage at all."""
    malicious = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    resp = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback", params={"error": malicious}
    )
    assert resp.status_code == 200
    assert "<script>" not in resp.text
    assert "<img" not in resp.text
    assert "&lt;script&gt;" in resp.text
    assert "&lt;img" in resp.text
    assert "cancelled" in resp.text.lower()


def test_callback_with_bad_state_shows_friendly_failure_page(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")
    resp = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback", params={"code": "c", "state": "nonexistent-state"}
    )
    assert resp.status_code == 200
    assert "failed" in resp.text.lower()


def test_callback_page_identifies_the_provider_and_offers_a_real_return_link(client_with_fake_integrations: TestClient) -> None:
    """Phase 6 diagnostic pass (D75-series): the callback page must name
    which provider failed/succeeded and link back to a real, reachable
    destination — `/?open=integrations`, which App.tsx's deep-link
    handling turns into an actual Integrations Centre open, not a bare
    '/' the user has to manually navigate from."""
    resp = client_with_fake_integrations.get("/api/integrations/google_calendar/oauth/callback")
    assert resp.status_code == 200
    assert "Google Calendar" in resp.text
    assert 'href="/?open=integrations"' in resp.text


def test_callback_page_diagnostic_ring_animates_differently_for_success_vs_failure(
    client_with_fake_integrations: TestClient, fake_credential_store
) -> None:
    """The callback page's diagnostic ring previously never animated at
    all. Success now spins continuously (a real "it's working" signal);
    failure gets one deliberate partial turn that decelerates into a
    stop — a real, state-driven motion, never a frozen image and never a
    continuous spin implying "still trying" when it already failed."""
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")

    start_resp = client_with_fake_integrations.post("/api/integrations/google_calendar/connect", json={"include_write_scope": False})
    auth_url = start_resp.json()["authorization_url"]
    state = httpx.QueryParams(httpx.URL(auth_url).query.decode())["state"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": "calendar.readonly"})

    client_with_fake_integrations.app.state.integration_http_client = httpx.Client(transport=httpx.MockTransport(handler))

    # The <style> block unconditionally defines both animation classes —
    # only the <svg>'s own class attribute says which one actually
    # applies, so assert on that exact attribute, not a bare substring
    # (which the CSS rule definitions would also match either way).
    success_resp = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback", params={"code": "authcode", "state": state}
    )
    assert 'class="diag-ring diag-ring-spin"' in success_resp.text
    assert 'class="diag-ring diag-ring-turn-stop"' not in success_resp.text

    failure_resp = client_with_fake_integrations.get("/api/integrations/google_calendar/oauth/callback")
    assert 'class="diag-ring diag-ring-turn-stop"' in failure_resp.text
    assert 'class="diag-ring diag-ring-spin"' not in failure_resp.text


def test_callback_page_never_renders_the_oauth_code_or_state_values(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")
    resp = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback",
        params={"code": "super-secret-auth-code-value", "state": "nonexistent-state"},
    )
    assert resp.status_code == 200
    assert "super-secret-auth-code-value" not in resp.text
    assert "nonexistent-state" not in resp.text


def test_cancelled_callback_offers_try_again_but_a_genuine_failure_does_not(
    client_with_fake_integrations: TestClient, fake_credential_store
) -> None:
    # Cancelled (no code/state at all) — retrying is a safe, sensible next
    # step, so "Try connection again" is offered.
    cancelled = client_with_fake_integrations.get("/api/integrations/google_calendar/oauth/callback")
    assert "Try connection again" in cancelled.text

    # A genuine exchange failure — blindly retrying the same broken state
    # isn't offered as if it were a safe distinct action.
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")
    failed = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback", params={"code": "c", "state": "nonexistent-state"}
    )
    assert "Try connection again" not in failed.text


def test_full_connect_flow_over_http(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    integration_service.store_client_credentials(fake_credential_store, "google_calendar", client_id="cid", client_secret="csecret")

    start_resp = client_with_fake_integrations.post("/api/integrations/google_calendar/connect", json={"include_write_scope": False})
    auth_url = start_resp.json()["authorization_url"]
    state = httpx.QueryParams(httpx.URL(auth_url).query.decode())["state"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT1", "expires_in": 3600, "scope": "calendar.readonly"})

    client_with_fake_integrations.app.state.integration_http_client = httpx.Client(transport=httpx.MockTransport(handler))

    callback_resp = client_with_fake_integrations.get(
        "/api/integrations/google_calendar/oauth/callback", params={"code": "authcode", "state": state}
    )
    assert callback_resp.status_code == 200
    assert "connected" in callback_resp.text.lower()

    status_resp = client_with_fake_integrations.get("/api/integrations")
    statuses = {row["provider"]: row["status"] for row in status_resp.json()}
    assert statuses["google_calendar"] == "connected"


def test_disconnect_over_http(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    fake_credential_store.set("google_calendar", "access_token", "AT1")
    resp = client_with_fake_integrations.post("/api/integrations/google_calendar/disconnect")
    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"
    assert fake_credential_store.get("google_calendar", "access_token") is None


def test_google_health_unsupported_metrics_endpoint(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.get("/api/integrations/google_health/unsupported-metrics")
    assert resp.status_code == 200
    assert "Daily Readiness Score" in resp.json()


def test_legacy_fitbit_endpoints_no_longer_exist(client_with_fake_integrations: TestClient) -> None:
    assert client_with_fake_integrations.get("/api/integrations/fitbit/unsupported-metrics").status_code == 404
    assert client_with_fake_integrations.get("/api/integrations/fitbit/oauth/callback").status_code == 404
    assert client_with_fake_integrations.post("/api/integrations/fitbit/connect", json={}).status_code == 404


def test_no_token_material_in_any_integration_response(client_with_fake_integrations: TestClient, fake_credential_store) -> None:
    fake_credential_store.set("google_calendar", "access_token", "SUPER-SECRET-TOKEN")
    resp = client_with_fake_integrations.get("/api/integrations")
    assert "SUPER-SECRET-TOKEN" not in resp.text


def test_one_provider_status_failure_does_not_break_the_other_providers_result(
    client_with_fake_integrations: TestClient, monkeypatch
) -> None:
    """Real incident this fixes (docs/DECISIONS.md D66): a failure
    unrelated to connection status must never make a healthy provider look
    disconnected, and must never take down the whole endpoint."""
    from app.routers import integrations as integrations_router

    real_get_connection = integrations_router.integration_service.get_connection

    def flaky_get_connection(db, provider):
        if provider == "google_health":
            raise RuntimeError("simulated unexpected failure")
        return real_get_connection(db, provider)

    monkeypatch.setattr(integrations_router.integration_service, "get_connection", flaky_get_connection)

    resp = client_with_fake_integrations.get("/api/integrations")
    assert resp.status_code == 200
    by_provider = {row["provider"]: row for row in resp.json()}
    assert by_provider["google_calendar"]["status"] == "disconnected"  # untouched, genuinely disconnected
    assert by_provider["google_health"]["status"] == "error"  # never "disconnected" for an unrelated failure
    assert "simulated unexpected failure" in (by_provider["google_health"]["last_error"] or "")


def test_schedule_defaults_disabled_over_http(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.get("/api/integrations/google_calendar/schedule")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["next_due_at"] is None


def test_schedule_enable_rejects_invalid_interval_over_http(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.put(
        "/api/integrations/google_calendar/schedule", json={"enabled": True, "interval_minutes": 5}
    )
    assert resp.status_code == 400


def test_schedule_enable_over_http_schedules_immediate_sync(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.put(
        "/api/integrations/google_calendar/schedule", json={"enabled": True, "interval_minutes": 15}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["next_due_at"] is not None


def test_sync_history_endpoint_returns_bounded_list(client_with_fake_integrations: TestClient) -> None:
    resp = client_with_fake_integrations.get("/api/integrations/google_health/sync-history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_unknown_provider_schedule_endpoints_404(client_with_fake_integrations: TestClient) -> None:
    assert client_with_fake_integrations.get("/api/integrations/fitbit/schedule").status_code == 404
    assert client_with_fake_integrations.get("/api/integrations/fitbit/sync-history").status_code == 404


def test_list_integrations_never_touches_the_credential_store(client_with_fake_integrations: TestClient) -> None:
    """A pure status read must never access Keychain — confirmed by using
    a store that raises on any access; the endpoint must still succeed."""

    class _ExplodingStore:
        def get(self, provider, key):
            raise AssertionError("list_integrations must never read the credential store")

        def set(self, provider, key, value):
            raise AssertionError("list_integrations must never write the credential store")

        def delete(self, provider, key):
            raise AssertionError("list_integrations must never delete from the credential store")

        def delete_all(self, provider, keys):
            raise AssertionError("list_integrations must never delete from the credential store")

    client_with_fake_integrations.app.state.credential_store = _ExplodingStore()
    resp = client_with_fake_integrations.get("/api/integrations")
    assert resp.status_code == 200
