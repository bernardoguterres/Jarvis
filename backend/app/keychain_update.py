"""In-place macOS Keychain updates via `SecItemUpdate`.

`keyring`'s macOS backend deletes and recreates the item on every write,
which resets its access list and wipes any "Always Allow" grant, so every
token refresh caused a new Keychain prompt. Updating in place keeps the
item, and its grant, intact.

Reuses `keyring.backends.macOS.api`'s ctypes bindings and adds only
`SecItemUpdate`. The new value must be a real `CFDataRef`; the
`CFStringRef` that `create_query` produces is rejected with
`errSecParam` (-50).
"""

from __future__ import annotations

import ctypes
import platform
from ctypes import c_int32, c_void_p


class KeychainUpdateNotSupported(Exception):
    """Raised when this platform (or the Security framework) isn't
    available. The caller falls back to keyring's own create/update path,
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
    create it through the normal path, since a brand-new item has no ACL to
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
