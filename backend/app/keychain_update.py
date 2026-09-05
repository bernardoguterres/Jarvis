"""In-place macOS Keychain item updates via `SecItemUpdate`.

`keyring`'s own macOS backend (`keyring.backends.macOS.api.set_generic_password`)
always deletes and recreates a generic-password item on every write, which
resets the item's Access Control list — silently wiping any "Always Allow"
grant a user has already given the signed backend binary, causing a fresh
Keychain permission prompt on the next read after every OAuth token
refresh. An in-place update via `SecItemUpdate` changes only the stored
value; the item's identity (and therefore its ACL) is never touched, so a
grant made once survives every later token refresh.

Reuses `keyring.backends.macOS.api`'s own ctypes bindings (same libraries,
same query-building helpers) rather than reimplementing them, adding only
the one binding `keyring` doesn't need: `SecItemUpdate`. Its
`attributesToUpdate` dictionary requires a genuine `CFDataRef` for
`kSecValueData` — `create_query`'s generic value coercion produces a
`CFStringRef` instead, which `SecItemAdd` tolerates but `SecItemUpdate`
rejects with `errSecParam`/-50. See docs/DECISIONS.md for the disposable-item
verification this passed before being used against a real credential.
"""

from __future__ import annotations

import ctypes
import platform
from ctypes import c_int32, c_void_p


class KeychainUpdateNotSupported(Exception):
    """Raised when this platform (or the Security framework) isn't
    available — the caller falls back to keyring's own create/update path,
    which has no ACL-preservation benefit but still works correctly."""


def _load_api():
    if platform.system() != "Darwin":
        raise KeychainUpdateNotSupported("Not running on macOS")
    try:
        from keyring.backends.macOS import api
    except Exception as exc:  # pragma: no cover - keyring's own import guard
        raise KeychainUpdateNotSupported("keyring's macOS Security bindings are unavailable") from exc
    return api


def update_generic_password_in_place(service: str, account: str, value: str) -> bool:
    """Updates an existing generic-password item's value in place, without
    deleting/recreating it. Returns True if an existing item was found and
    updated; False if no such item exists yet (the caller should then
    create it through the normal path — a brand-new item has no ACL to
    preserve). Raises on any other Keychain error."""
    api = _load_api()

    SecItemUpdate = api._sec.SecItemUpdate
    SecItemUpdate.restype = api.OS_status
    SecItemUpdate.argtypes = (c_void_p, c_void_p)

    CFDataCreate = api._found.CFDataCreate
    CFDataCreate.restype = c_void_p
    CFDataCreate.argtypes = (c_void_p, c_void_p, c_int32)

    def _cfdata(data: bytes) -> c_void_p:
        buf = ctypes.create_string_buffer(data, len(data))
        return CFDataCreate(None, buf, len(data))

    query = api.create_query(
        kSecClass=api.k_("kSecClassGenericPassword"),
        kSecAttrService=service,
        kSecAttrAccount=account,
    )
    keys = (c_void_p * 1)(api.k_("kSecValueData"))
    values = (c_void_p * 1)(_cfdata(value.encode("utf-8")))
    attributes_to_update = api._found.CFDictionaryCreate(
        None,
        keys,
        values,
        1,
        api._found.kCFTypeDictionaryKeyCallBacks,
        api._found.kCFTypeDictionaryValueCallBacks,
    )

    status = SecItemUpdate(query, attributes_to_update)
    if status == api.error.item_not_found:
        return False
    api.Error.raise_for_status(status)
    return True
