"""A credential-store abstraction backed by macOS Keychain.

OAuth client credentials, access tokens, refresh tokens, and any token
metadata that could grant access live ONLY here, never in SQLite, `.env`,
source files, frontend state, logs, exports, or backups (CLAUDE.md §5,
docs/ARCHITECTURE.md). Automated tests must always use FakeCredentialStore,
never the real Keychain.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("jarvis.credential_store")

SERVICE_PREFIX = "jarvis"


class CredentialStore(Protocol):
    def set(self, provider: str, key: str, value: str) -> None: ...

    def get(self, provider: str, key: str) -> str | None: ...

    def delete(self, provider: str, key: str) -> None: ...

    def delete_all(self, provider: str, keys: list[str]) -> None: ...


def _default_data_dir() -> Path:
    return (Path.home() / "JarvisData").resolve()


def is_default_data_dir(data_dir: Path) -> bool:
    """True when `data_dir` is the real installation's folder, however it
    is spelled: `~`, relative paths, trailing slashes and symlinks are
    resolved, and an existing folder is compared by identity (inode), so a
    case variant on macOS's case-insensitive volume counts as the same
    folder."""
    resolved = Path(data_dir).expanduser().resolve()
    default = _default_data_dir()
    if resolved == default:
        return True
    if resolved.exists() and default.exists():
        try:
            return os.path.samefile(resolved, default)
        except OSError:
            return False
    return str(resolved).casefold() == str(default).casefold()


def keychain_namespace_for(data_dir: Path) -> str | None:
    """Keychain items are global to the macOS user, not to a data folder.
    Without a namespace, a Jarvis started against a throwaway
    JARVIS_DATA_DIR (a test, a reproduction, a second instance) reads and
    can revoke or delete the real installation's OAuth tokens; this
    happened once during an audit (D114). The default ~/JarvisData keeps
    the original unsuffixed names so the real installation's existing
    items are unchanged. Any other folder gets a stable suffix derived
    from its resolved, case-folded path. There is no fallback from a
    namespaced name to the unsuffixed one."""
    if is_default_data_dir(data_dir):
        return None
    resolved = str(Path(data_dir).expanduser().resolve()).casefold()
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]


def build_credential_store(data_dir: Path) -> "CredentialStore":
    """The store the app uses. JARVIS_CREDENTIAL_STORE=memory selects an
    in-memory store that never touches the Keychain; the test suite sets it
    in the environment, so it also reaches subprocesses (a spawned backend,
    a packaged sidecar under acceptance testing)."""
    if os.environ.get("JARVIS_CREDENTIAL_STORE", "").strip().lower() == "memory":
        logger.warning("JARVIS_CREDENTIAL_STORE=memory: using an in-memory credential store, not the Keychain.")
        return FakeCredentialStore()
    return KeychainCredentialStore(namespace=keychain_namespace_for(data_dir))


class KeychainCredentialStore:
    """Real implementation, backed by the `keyring` package (macOS Keychain
    on this platform). Never logs or returns the values it stores/reads.
    `namespace` comes from keychain_namespace_for(); None means the real
    default installation."""

    def __init__(self, namespace: str | None = None) -> None:
        self._namespace = namespace

    def _service_name(self, provider: str) -> str:
        base = f"{SERVICE_PREFIX}.{provider}"
        return f"{base}.{self._namespace}" if self._namespace else base

    def set(self, provider: str, key: str, value: str) -> None:
        # `keyring.set_password` deletes and recreates the Keychain item on
        # every write (see keyring.backends.macOS.api.set_generic_password),
        # which resets the item's Access Control list (wiping any "Always
        # Allow" grant) every time an OAuth token is refreshed. Update the
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
            updated = False  # not on macOS (or Security framework unavailable); fall back below
        if updated:
            # Never log `value`. Provider/key names alone (e.g.
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
            pass  # already absent; deletion is idempotent

    def delete_all(self, provider: str, keys: list[str]) -> None:
        for key in keys:
            self.delete(provider, key)


class FakeCredentialStore:
    """In-memory stand-in for automated tests. Never touches the real
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
