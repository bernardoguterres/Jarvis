"""OAuth state/PKCE bookkeeping: single-use, bounded lifetime, replay
rejection, provider-mismatch rejection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.oauth_flow import OAuthFlowError, OAuthFlowStore, pkce_challenge_from_verifier


def test_pkce_challenge_is_deterministic_and_not_the_verifier() -> None:
    challenge1 = pkce_challenge_from_verifier("abc123")
    challenge2 = pkce_challenge_from_verifier("abc123")
    assert challenge1 == challenge2
    assert challenge1 != "abc123"


def test_start_and_consume_happy_path() -> None:
    store = OAuthFlowStore()
    flow = store.start("fitbit", "http://127.0.0.1:8000/api/integrations/fitbit/oauth/callback")
    consumed = store.consume(flow.state, provider="fitbit")
    assert consumed.code_verifier == flow.code_verifier


def test_state_is_single_use_replay_rejected() -> None:
    store = OAuthFlowStore()
    flow = store.start("fitbit", "http://127.0.0.1:8000/x")
    store.consume(flow.state, provider="fitbit")
    with pytest.raises(OAuthFlowError):
        store.consume(flow.state, provider="fitbit")


def test_unknown_state_rejected() -> None:
    store = OAuthFlowStore()
    with pytest.raises(OAuthFlowError):
        store.consume("not-a-real-state", provider="fitbit")


def test_provider_mismatch_rejected() -> None:
    store = OAuthFlowStore()
    flow = store.start("fitbit", "http://127.0.0.1:8000/x")
    with pytest.raises(OAuthFlowError):
        store.consume(flow.state, provider="google_calendar")


def test_expired_state_rejected() -> None:
    store = OAuthFlowStore()
    flow = store.start("fitbit", "http://127.0.0.1:8000/x")
    flow.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    with pytest.raises(OAuthFlowError):
        store.consume(flow.state, provider="fitbit")


def test_each_flow_gets_a_unique_state_and_verifier() -> None:
    store = OAuthFlowStore()
    flow_a = store.start("fitbit", "http://127.0.0.1:8000/x")
    flow_b = store.start("fitbit", "http://127.0.0.1:8000/x")
    assert flow_a.state != flow_b.state
    assert flow_a.code_verifier != flow_b.code_verifier
