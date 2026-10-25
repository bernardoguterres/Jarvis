"""Regression tests for the loopback API protection (app/local_api_guard.py).

Before the guard, a cross-origin multipart POST /api/restore with
confirm=true replaced the database, body-less cross-origin POSTs ran, and a
foreign Host header was served (the DNS-rebinding precondition). These
tests send requests the way a hostile page or a rebinding attacker would
and check the server refuses them before any handler runs, using
independent state checks (memory rows on disk) rather than status codes
alone.
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.export_service import create_export

EVIL = "https://evil.example"


def _bare(client: TestClient, **kwargs) -> TestClient:
    """Same app, no token, loopback Host unless overridden."""
    return TestClient(client.app, base_url=kwargs.pop("base_url", "http://127.0.0.1:8000"), **kwargs)


def _memory_titles(data_dir: Path) -> list[str]:
    conn = sqlite3.connect(str(data_dir / "database" / "jarvis.sqlite"))
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT v.title FROM memory_items m JOIN memory_versions v ON v.id = m.current_version_id"
            )
        ]
    finally:
        conn.close()


def _create_memory(client: TestClient, title: str) -> None:
    r = client.post(
        "/api/memories", json={"scope": "global", "kind": "fact", "title": title, "content": "c"}
    )
    assert r.status_code == 201, r.text


def test_foreign_host_is_refused_even_with_a_valid_token(client: TestClient) -> None:
    token = client.app.state.api_token
    rebinding = TestClient(client.app, base_url="http://rebind.attacker.example:8000")
    r = rebinding.get("/api/memories", headers={"X-Jarvis-Token": token})
    assert r.status_code == 403
    assert rebinding.get("/api/session").status_code == 403
    assert rebinding.get("/").status_code == 403


def test_loopback_hosts_are_accepted(client: TestClient) -> None:
    token = client.app.state.api_token
    for base in ("http://127.0.0.1:8000", "http://localhost:8000", "http://127.0.0.1:9123"):
        r = TestClient(client.app, base_url=base).get("/api/domains", headers={"X-Jarvis-Token": token})
        assert r.status_code == 200, base


def test_host_parsing() -> None:
    from app.local_api_guard import is_loopback_host

    assert is_loopback_host("[::1]:8000")
    assert is_loopback_host("LOCALHOST")
    assert not is_loopback_host("127.0.0.1.evil.example")
    assert not is_loopback_host("localhost.evil.example:8000")
    assert not is_loopback_host("")
    assert not is_loopback_host(None)


def test_missing_or_wrong_token_is_refused(client: TestClient) -> None:
    bare = _bare(client)
    assert bare.get("/api/memories").status_code == 401
    assert bare.get("/api/memories", headers={"X-Jarvis-Token": "wrong"}).status_code == 401
    assert bare.post("/api/integrations/google_calendar/disconnect").status_code == 401


def test_health_is_public_and_session_returns_the_token_uncached(client: TestClient) -> None:
    bare = _bare(client)
    assert bare.get("/api/health").json() == {"status": "ok"}
    r = bare.get("/api/session")
    assert r.status_code == 200
    assert r.json()["token"] == client.app.state.api_token
    assert r.headers["cache-control"] == "no-store"


def test_token_bootstrap_refused_to_cross_site_and_foreign_origin(client: TestClient) -> None:
    bare = _bare(client)
    assert bare.get("/api/session", headers={"Origin": EVIL}).status_code == 403
    assert bare.get("/api/session", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    # The configured Vite dev origin may bootstrap (a CORS fetch always sends Origin).
    dev = get_settings().cors_origin
    r = bare.get("/api/session", headers={"Origin": dev, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == dev


def test_cross_origin_restore_is_refused_and_data_is_untouched(client: TestClient, data_dir: Path) -> None:
    _create_memory(client, "victim-memory")
    archive = create_export(get_settings()).path

    with archive.open("rb") as handle:
        payload = handle.read()
    attacker = _bare(client)
    r = attacker.post(
        "/api/restore",
        headers={"Origin": EVIL},
        files={"file": ("x.zip", io.BytesIO(payload), "application/zip")},
        data={"confirm": "true"},
    )
    assert r.status_code == 403
    # A no-Origin request (an old browser, or a form with Origin stripped)
    # still has no token.
    r = attacker.post(
        "/api/restore",
        files={"file": ("x.zip", io.BytesIO(payload), "application/zip")},
        data={"confirm": "true"},
    )
    assert r.status_code == 401
    assert _memory_titles(data_dir) == ["victim-memory"]


def test_foreign_origin_refused_even_with_token(client: TestClient) -> None:
    r = client.post(
        "/api/memories",
        headers={"Origin": EVIL},
        json={"scope": "global", "kind": "fact", "title": "x", "content": "c"},
    )
    assert r.status_code == 403
    assert client.post("/api/memories", headers={"Origin": "null"}, json={}).status_code == 403


def test_same_origin_and_dev_origin_requests_work(client: TestClient) -> None:
    _create_memory(client, "ok")
    assert client.get("/api/memories", headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200
    assert client.get("/api/memories", headers={"Origin": get_settings().cors_origin}).status_code == 200


def test_preflight_refuses_foreign_origin_and_allows_token_header_for_dev(client: TestClient) -> None:
    bare = _bare(client)
    evil = bare.options(
        "/api/memories",
        headers={
            "Origin": EVIL,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-jarvis-token,content-type",
        },
    )
    assert "access-control-allow-origin" not in evil.headers
    dev = get_settings().cors_origin
    ok = bare.options(
        "/api/memories",
        headers={
            "Origin": dev,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-jarvis-token,content-type",
        },
    )
    assert ok.status_code == 200
    assert "x-jarvis-token" in ok.headers["access-control-allow-headers"].lower()


def test_export_download_link_works_same_origin_but_not_cross_site(client: TestClient) -> None:
    created = client.post("/api/export")
    assert created.status_code == 201
    filename = created.json()["filename"]
    bare = _bare(client)
    path = f"/api/exports/{filename}/download"
    assert bare.get(path, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert bare.get(path).status_code == 200  # address bar / older engines send no fetch metadata
    assert bare.get(path, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 401


def test_oauth_callback_needs_no_token_but_still_needs_loopback_host(client: TestClient) -> None:
    bare = _bare(client)
    r = bare.get("/api/integrations/google_calendar/oauth/callback?state=unknown&code=x")
    assert r.status_code != 401
    foreign = TestClient(client.app, base_url="http://attacker.example")
    assert foreign.get("/api/integrations/google_calendar/oauth/callback?state=x").status_code == 403


def test_every_api_route_requires_the_token(client: TestClient) -> None:
    """Walks the real route table so a newly added route cannot silently
    skip the guard."""
    from fastapi.routing import APIRoute

    exempt = {
        "/api/health",
        "/api/integrations/google_calendar/oauth/callback",
        "/api/integrations/google_health/oauth/callback",
        "/api/exports/{filename}/download",
    }
    bare = _bare(client)
    checked = 0
    for route in client.app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/") or route.path in exempt:
            continue
        path = route.path
        for part in route.param_convertors:
            path = path.replace("{" + part + "}", "x")
        path = path.replace("{full_path:path}", "x")
        for method in route.methods:
            r = bare.request(method, path)
            assert r.status_code == 401, (method, route.path, r.status_code)
            checked += 1
    assert checked > 150
