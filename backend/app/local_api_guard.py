"""Protection for the loopback API against requests a web page sends.

CORS only decides which pages may read a response. It does not stop a
browser from delivering a cross-origin form POST, and it does nothing
about DNS rebinding. Every request therefore passes three checks here:

1. Host: the Host header must name a loopback address (127.0.0.1,
   localhost or ::1, any port). A DNS-rebinding page sends its own
   hostname, so it is refused before any handler runs.
2. Origin: when a browser sends an Origin header it must be this
   server's own origin or the configured dev origin (Vite). Anything
   else, including "null", is refused.
3. Token: every /api request must carry the per-launch token in the
   X-Jarvis-Token header. A foreign page cannot obtain it (it is only
   served to same-origin or allowlisted callers) and cannot send a
   custom header cross-origin without a CORS preflight, which is refused.

The token is generated in memory when the app object is created, is
never written to disk, logs, URLs or exports, and changes on every
launch. It does not protect against other programs running on this Mac:
they can ask for it like the app's own window does, and a process that
can do that can usually read JARVIS_DATA_DIR directly anyway.

A few routes cannot carry a custom header and are handled separately:
the health probe, the token bootstrap itself, the OAuth redirect
callbacks (top-level navigations from Google, protected by their own
single-use state value) and the export download link (a plain <a href>,
refused when the browser reports it as coming from another site).
"""

from __future__ import annotations

import hmac
import json
import re
import secrets

TOKEN_HEADER = "x-jarvis-token"
SESSION_PATH = "/api/session"

_LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
_PUBLIC_GET_PATHS = {"/api/health"}
_OAUTH_CALLBACK_PATHS = {
    "/api/integrations/google_calendar/oauth/callback",
    "/api/integrations/google_health/oauth/callback",
}
_EXPORT_DOWNLOAD_RE = re.compile(r"^/api/exports/[^/]+/download$")


def new_api_token() -> str:
    return secrets.token_urlsafe(32)


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def is_loopback_host(host_header: str | None) -> bool:
    return bool(host_header) and _hostname(host_header) in _LOOPBACK_HOSTNAMES


class LocalApiGuard:
    """Pure ASGI middleware, so it also covers static files and runs
    before FastAPI parses any request body (a refused multipart restore
    upload is never read)."""

    def __init__(self, app, *, token: str, extra_origins: list[str]) -> None:
        self.app = app
        self._token = token.encode("utf-8")
        self._extra_origins = {o.rstrip("/") for o in extra_origins if o}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host")
        if not is_loopback_host(host):
            await _deny(send, 403, "Host not allowed.")
            return

        origin = headers.get("origin")
        if origin is not None and origin.rstrip("/") not in ({f"http://{host}"} | self._extra_origins):
            await _deny(send, 403, "Origin not allowed.")
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if not path.startswith("/api/") or method == "OPTIONS":
            # Static frontend files, and CORS preflights (answered or
            # refused by CORSMiddleware, which never runs a handler).
            await self.app(scope, receive, send)
            return

        fetch_site = headers.get("sec-fetch-site")
        if method in ("GET", "HEAD"):
            if path in _PUBLIC_GET_PATHS or path in _OAUTH_CALLBACK_PATHS:
                await self.app(scope, receive, send)
                return
            if path == SESSION_PATH:
                if origin is None and fetch_site in ("cross-site", "same-site"):
                    await _deny(send, 403, "Cross-site token request refused.")
                    return
                await _send_json(send, 200, {"token": self._token.decode("utf-8")}, no_store=True)
                return
            if _EXPORT_DOWNLOAD_RE.match(path) and fetch_site in (None, "same-origin", "none"):
                await self.app(scope, receive, send)
                return

        supplied = headers.get(TOKEN_HEADER, "").encode("utf-8")
        if not supplied or not hmac.compare_digest(supplied, self._token):
            await _deny(send, 401, "Missing or invalid Jarvis API token.")
            return

        await self.app(scope, receive, send)


async def _deny(send, status: int, detail: str) -> None:
    await _send_json(send, status, {"detail": detail})


async def _send_json(send, status: int, body: dict, *, no_store: bool = False) -> None:
    payload = json.dumps(body).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode("ascii")),
        (b"x-content-type-options", b"nosniff"),
    ]
    if no_store:
        headers.append((b"cache-control", b"no-store"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
