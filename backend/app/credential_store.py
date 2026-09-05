"""Phase 9: a credential-store abstraction backed by macOS Keychain.

OAuth client credentials, access tokens, refresh tokens, and any token
metadata that could grant access live ONLY here — never in SQLite, `.env`,
source files, frontend state, logs, exports, or backups (CLAUDE.md §5,
docs/ARCHITECTURE.md). Automated tests must always use FakeCredentialStore,
never the real Keychain.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("jarvis.credential_store")

SERVICE_PREFIX = "jarvis"


class CredentialStore(Protocol):
    def set(self, provider: str, key: str, value: str) -> None: ...

    def get(self, provider: str, key: str) -> str | None: ...

    def delete(self, provider: str, key: str) -> None: ...

    def delete_all(self, provider: str, keys: list[str]) -> None: ...


class KeychainCredentialStore:
    """Real implementation, backed by the `keyring` package (macOS Keychain
    on this platform). Never logs or returns the values it stores/reads."""

    def _service_name(self, provider: str) -> str:
        return f"{SERVICE_PREFIX}.{provider}"

    def set(self, provider: str, key: str, value: str) -> None:
        # `keyring.set_password` deletes and recreates the Keychain item on
        # every write (see keyring.backends.macOS.api.set_generic_password),
        # which resets the item's Access Control list — wiping any "Always
        # Allow" grant — every time an OAuth token is refreshed. Update the
        # item in place instead when it already exists; only fall back to
        # keyring's create path for a genuinely new item, which has no ACL
        # to preserve yet. Proven against a disposable, uniquely-named test
        # item before ever touching a real credential (see
        # docs/DECISIONS.md's Keychain-recurring-prompt entry).
        from app.keychain_update import KeychainUpdateNotSupported, update_generic_password_in_place

        service = self._service_name(provider)
        try:
            updated = update_generic_password_in_place(service, key, value)
        except KeychainUpdateNotSupported:
            updated = False  # not on macOS (or Security framework unavailable) — fall back below
        if updated:
            # Never log `value` — provider/key names alone (e.g.
            # "google_calendar"/"access_token") are already visible via
            # GET /api/integrations and carry no secret.
            logger.info("Keychain write for %s/%s used in-place update (ACL preserved).", provider, key)
            return

        import keyring

        keyring.set_password(service, key, value)
        logger.info(
            "Keychain write for %s/%s used the create path (no existing item to update) — its ACL may need re-approval once.",
            provider,
            key,
        )

    def get(self, provider: str, key: str) -> str | None:
        import keyring

        return keyring.get_password(self._service_name(provider), key)

    def delete(self, provider: str, key: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(self._service_name(provider), key)
        except PasswordDeleteError:
            pass  # already absent — deletion is idempotent

    def delete_all(self, provider: str, keys: list[str]) -> None:
        for key in keys:
            self.delete(provider, key)


class FakeCredentialStore:
    """In-memory stand-in for automated tests — never touches the real
    Keychain. Also useful for asserting exactly what a test wrote/read."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}

    def set(self, provider: str, key: str, value: str) -> None:
        self._data[(provider, key)] = value

    def get(self, provider: str, key: str) -> str | None:
        return self._data.get((provider, key))

    def delete(self, provider: str, key: str) -> None:
        self._data.pop((provider, key), None)

    def delete_all(self, provider: str, keys: list[str]) -> None:
        for key in keys:
            self.delete(provider, key)
