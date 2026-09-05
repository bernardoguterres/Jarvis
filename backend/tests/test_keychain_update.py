"""app.keychain_update's platform guard — never touches the real Keychain
(the actual SecItemUpdate call was verified against a real, disposable,
uniquely-named test item in a manual one-off check; see
docs/DECISIONS.md)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.keychain_update import KeychainUpdateNotSupported, update_generic_password_in_place


def test_raises_not_supported_on_a_non_macos_platform() -> None:
    with patch("platform.system", return_value="Linux"):
        with pytest.raises(KeychainUpdateNotSupported):
            update_generic_password_in_place("jarvis.google_calendar", "access_token", "value")
