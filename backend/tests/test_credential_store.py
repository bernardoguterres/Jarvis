"""FakeCredentialStore behavior — automated tests never touch the real
macOS Keychain (see docs/DECISIONS.md).

KeychainCredentialStore.set()'s own control flow (try in-place update,
fall back to keyring's create path) is tested below with the real
Security-framework call mocked out entirely — still never touching the
real Keychain. The in-place update mechanism itself was verified against a
real, disposable, uniquely-named Keychain item in a manual one-off
verification (not part of this automated suite, per the rule above) — see
docs/DECISIONS.md."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.credential_store import FakeCredentialStore, KeychainCredentialStore
from app.keychain_update import KeychainUpdateNotSupported


def test_set_get_roundtrip() -> None:
    store = FakeCredentialStore()
    store.set("fitbit", "access_token", "secret-value")
    assert store.get("fitbit", "access_token") == "secret-value"


def test_get_missing_returns_none() -> None:
    store = FakeCredentialStore()
    assert store.get("fitbit", "access_token") is None


def test_delete_is_idempotent() -> None:
    store = FakeCredentialStore()
    store.set("fitbit", "access_token", "x")
    store.delete("fitbit", "access_token")
    assert store.get("fitbit", "access_token") is None
    store.delete("fitbit", "access_token")  # second delete must not raise


def test_providers_are_isolated_from_each_other() -> None:
    store = FakeCredentialStore()
    store.set("fitbit", "access_token", "fitbit-token")
    store.set("google_calendar", "access_token", "calendar-token")
    assert store.get("fitbit", "access_token") == "fitbit-token"
    assert store.get("google_calendar", "access_token") == "calendar-token"


def test_delete_all() -> None:
    store = FakeCredentialStore()
    store.set("fitbit", "access_token", "a")
    store.set("fitbit", "refresh_token", "b")
    store.delete_all("fitbit", ["access_token", "refresh_token"])
    assert store.get("fitbit", "access_token") is None
    assert store.get("fitbit", "refresh_token") is None


class TestKeychainCredentialStoreSetControlFlow:
    """KeychainCredentialStore.set()'s decision logic — mocked at the
    app.keychain_update seam, never touching the real Keychain. Regression
    tests for the fix to keyring's own delete-then-recreate write
    semantics, which reset a Keychain item's Access Control list (wiping
    an "Always Allow" grant) on every OAuth token refresh."""

    def test_set_uses_in_place_update_when_the_item_already_exists(self) -> None:
        store = KeychainCredentialStore()
        with (
            patch("app.keychain_update.update_generic_password_in_place", return_value=True) as mock_update,
            patch("keyring.set_password") as mock_keyring_set,
        ):
            store.set("google_calendar", "access_token", "new-value")

        mock_update.assert_called_once_with("jarvis.google_calendar", "access_token", "new-value")
        mock_keyring_set.assert_not_called()  # never falls through to the ACL-resetting path

    def test_set_falls_back_to_keyring_when_no_existing_item(self) -> None:
        store = KeychainCredentialStore()
        with (
            patch("app.keychain_update.update_generic_password_in_place", return_value=False) as mock_update,
            patch("keyring.set_password") as mock_keyring_set,
        ):
            store.set("google_calendar", "access_token", "first-value")

        mock_update.assert_called_once()
        mock_keyring_set.assert_called_once_with("jarvis.google_calendar", "access_token", "first-value")

    def test_set_falls_back_to_keyring_when_the_platform_is_unsupported(self) -> None:
        store = KeychainCredentialStore()
        with (
            patch(
                "app.keychain_update.update_generic_password_in_place",
                side_effect=KeychainUpdateNotSupported("not macOS"),
            ),
            patch("keyring.set_password") as mock_keyring_set,
        ):
            store.set("google_calendar", "access_token", "value")

        mock_keyring_set.assert_called_once_with("jarvis.google_calendar", "access_token", "value")

    def test_set_propagates_a_genuine_keychain_error_without_falling_back(self) -> None:
        # A real error (permission denied, corrupt item, etc.) must never
        # be silently swallowed into a fallback create attempt — only the
        # specific "no such item yet" case (False) and "unsupported
        # platform" case fall back.
        store = KeychainCredentialStore()
        with (
            patch("app.keychain_update.update_generic_password_in_place", side_effect=RuntimeError("boom")),
            patch("keyring.set_password") as mock_keyring_set,
            pytest.raises(RuntimeError, match="boom"),
        ):
            store.set("google_calendar", "access_token", "value")

        mock_keyring_set.assert_not_called()
