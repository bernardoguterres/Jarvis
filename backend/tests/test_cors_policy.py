"""Regression tests for the CORS policy in `app.main.create_app` (D82).

Context: a Phase 11 security review (D81) found that `allow_methods` omitted
PUT, which blocks a cross-origin `npm run dev` (port 5173 -> 8000) call to a
real, already-shipped PUT endpoint (domain summary, integration schedule,
routine schedule) at the browser preflight stage — invisible in production,
since Phase 7 serves the frontend same-origin and no preflight ever happens
there. D82 added PUT to the explicit allow-list. These tests exist so that
fix can never silently regress, and so the policy can never quietly drift
toward a wildcard origin/method list instead of an explicit one.

These are the FastAPI/Starlette CORS *policy* being exercised directly via
an OPTIONS preflight and matching Origin headers — not a real browser, which
is the one thing that actually enforces the resulting headers. That
enforcement itself was verified live in D82 (see docs/DECISIONS.md).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

APPROVED_ORIGIN = "http://localhost:5173"
UNAPPROVED_ORIGIN = "http://evil.example.com"


def test_preflight_for_put_succeeds_from_the_approved_dev_origin(client: TestClient) -> None:
    """The exact gap D82 fixed: a PUT-using endpoint's preflight must now
    succeed from the one approved local dev origin."""
    response = client.options(
        "/api/domains/body/summary",
        headers={
            "Origin": APPROVED_ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == APPROVED_ORIGIN
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_existing_allowed_methods_still_work(client: TestClient) -> None:
    """GET and POST preflights — already relied upon by every existing
    endpoint — must be unaffected by adding PUT."""
    for method in ("GET", "POST"):
        response = client.options(
            "/api/domains",
            headers={
                "Origin": APPROVED_ORIGIN,
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 200, method
        assert method in response.headers["access-control-allow-methods"]


def test_put_is_not_available_to_an_unapproved_origin(client: TestClient) -> None:
    """The fix must not broaden *who* can call PUT — only the one already-
    approved dev origin — so an arbitrary origin's preflight must still be
    refused."""
    response = client.options(
        "/api/domains/body/summary",
        headers={
            "Origin": UNAPPROVED_ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    # Starlette's CORSMiddleware returns 400 for a disallowed origin's
    # preflight, and never echoes that origin back in an
    # access-control-allow-origin header.
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_policy_has_no_wildcard_origin_or_method(client: TestClient) -> None:
    """A real browser only enforces what the preflight response actually
    says — so the policy itself, not just one probe, must stay an explicit
    allow-list. Guards against a future edit accidentally widening this to
    "*" (which `allow_credentials=False` would technically permit)."""
    response = client.options(
        "/api/domains/body/summary",
        headers={
            "Origin": APPROVED_ORIGIN,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    allowed_origin = response.headers["access-control-allow-origin"]
    allowed_methods = response.headers["access-control-allow-methods"]
    assert allowed_origin != "*"
    assert allowed_origin == APPROVED_ORIGIN
    assert allowed_methods != "*"
    assert set(m.strip() for m in allowed_methods.split(",")) == {"GET", "POST", "PUT"}
    assert response.headers.get("access-control-allow-credentials") != "true"
