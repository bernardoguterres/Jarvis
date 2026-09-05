"""Phase 9: Authorization Code + PKCE flow bookkeeping.

State and PKCE verifiers are transient, single-use, bounded-lifetime
secrets tied to one in-progress OAuth attempt — not long-term credentials.
They are kept only in memory (never in SQLite, so they're structurally
never part of an export/backup — CLAUDE.md's export-exclusion list), and
are gone the moment they're consumed or expire.

The redirect target is this same FastAPI backend, on loopback only
(127.0.0.1), at a fixed path per provider — never a separately-bound
listener and never a non-loopback host, satisfying "loopback-only
callbacks" and "exact redirect validation" (an OAuth provider is
configured with this exact URL and will refuse any other).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

STATE_TTL = timedelta(minutes=10)


class OAuthFlowError(Exception):
    pass


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def pkce_challenge_from_verifier(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Returns (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)[:128]
    return verifier, pkce_challenge_from_verifier(verifier)


@dataclass
class PendingOAuthFlow:
    provider: str
    state: str
    code_verifier: str
    redirect_uri: str
    created_at: datetime
    used: bool = False

    def is_expired(self, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > self.created_at + STATE_TTL


class OAuthFlowStore:
    """In-memory, single-use, bounded-lifetime store for in-progress OAuth
    flows. Not persisted — a backend restart mid-flow simply fails that one
    attempt cleanly, which is the correct behavior for a transient secret."""

    def __init__(self) -> None:
        self._flows: dict[str, PendingOAuthFlow] = {}

    def start(self, provider: str, redirect_uri: str) -> PendingOAuthFlow:
        state = generate_state()
        verifier, _ = generate_pkce_pair()
        flow = PendingOAuthFlow(
            provider=provider,
            state=state,
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            created_at=datetime.now(timezone.utc),
        )
        self._flows[state] = flow
        return flow

    def consume(self, state: str, *, provider: str) -> PendingOAuthFlow:
        """Validates and immediately invalidates `state` — a second call
        with the same state always fails (replay rejection)."""
        flow = self._flows.get(state)
        if flow is None:
            raise OAuthFlowError("Unknown or already-used OAuth state.")
        # Remove immediately — single-use regardless of what happens next.
        del self._flows[state]

        if flow.used:
            raise OAuthFlowError("OAuth state has already been used.")
        if flow.provider != provider:
            raise OAuthFlowError("OAuth state does not match this provider.")
        if flow.is_expired():
            raise OAuthFlowError("OAuth state has expired.")
        return flow

    def discard_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [s for s, f in self._flows.items() if f.is_expired(now=now)]
        for s in expired:
            del self._flows[s]
