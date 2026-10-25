"""Credential isolation between the real installation and any other data
folder (D114).

The real Keychain is never touched here: every keyring call and the
in-place update helper are replaced by an instrumented in-memory backend
that already holds made-up "production" tokens under the real
installation's unsuffixed item names. The app runs with the real
KeychainCredentialStore class on a temporary data folder, and every HTTP
request it makes is recorded. The checks are independent of the store's
own logic: which item names were touched, whether production values ever
left the backend, and which Google endpoints were called.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.credential_store import (
    FakeCredentialStore,
    KeychainCredentialStore,
    build_credential_store,
    is_default_data_dir,
    keychain_namespace_for,
)

PROD_SECRETS = {"PROD-ACCESS", "PROD-REFRESH", "PROD-CLIENT-SECRET"}
PROVIDERS = ("google_calendar", "google_health")


class InstrumentedKeyring:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.touched: list[tuple[str, str, str]] = []
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for provider in PROVIDERS:
            base = f"jarvis.{provider}"
            self.items[(base, "access_token")] = "PROD-ACCESS"
            self.items[(base, "refresh_token")] = "PROD-REFRESH"
            self.items[(base, "access_token_expires_at")] = future
            self.items[(base, "client_id")] = "prod-client-id"
            self.items[(base, "client_secret")] = "PROD-CLIENT-SECRET"
        self.production_snapshot = dict(self.items)

    def get_password(self, service: str, account: str) -> str | None:
        self.touched.append(("get", service, account))
        return self.items.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.touched.append(("set", service, account))
        self.items[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.touched.append(("delete", service, account))
        from keyring.errors import PasswordDeleteError

        if (service, account) not in self.items:
            raise PasswordDeleteError("missing")
        del self.items[(service, account)]

    def update_in_place(self, service: str, account: str, value: str) -> bool:
        self.touched.append(("update", service, account))
        if (service, account) not in self.items:
            return False
        self.items[(service, account)] = value
        return True

    def production_untouched(self) -> bool:
        return all(self.items.get(k) == v for k, v in self.production_snapshot.items())

    def unsuffixed_access(self) -> list[tuple[str, str, str]]:
        return [t for t in self.touched if t[1] in {f"jarvis.{p}" for p in PROVIDERS}]


@pytest.fixture()
def keyring_backend(monkeypatch: pytest.MonkeyPatch) -> InstrumentedKeyring:
    backend = InstrumentedKeyring()
    monkeypatch.setattr("keyring.get_password", backend.get_password)
    monkeypatch.setattr("keyring.set_password", backend.set_password)
    monkeypatch.setattr("keyring.delete_password", backend.delete_password)
    monkeypatch.setattr("app.keychain_update.update_generic_password_in_place", backend.update_in_place)
    # Use the real Keychain store class for this test, on the instrumented backend.
    monkeypatch.delenv("JARVIS_CREDENTIAL_STORE", raising=False)
    return backend


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "TEST-ACCESS-2", "expires_in": 3600, "scope": ""})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200)
        return httpx.Response(500, json={"error": "not faked"})

    def bodies(self) -> str:
        return " ".join(r.content.decode("utf-8", "replace") + " " + str(r.url) + " " + str(r.headers) for r in self.requests)


def _app_on_test_dir(client: TestClient, recorder: Recorder):
    app = client.app
    app.state.integration_http_client = httpx.Client(transport=httpx.MockTransport(recorder.handler))
    with app.state.session_factory() as db:
        from app.models_integrations import IntegrationConnection

        for provider in PROVIDERS:
            row = db.get(IntegrationConnection, provider) or IntegrationConnection(provider=provider, scopes_json="[]")
            row.status = "connected"
            db.add(row)
        db.commit()
    return app


def test_store_on_a_test_data_dir_is_namespaced(keyring_backend: InstrumentedKeyring, client: TestClient) -> None:
    store = client.app.state.credential_store
    assert isinstance(store, KeychainCredentialStore)
    assert store._namespace and len(store._namespace) == 12


def test_test_instance_never_reads_revokes_or_deletes_production_credentials(
    keyring_backend: InstrumentedKeyring, client: TestClient, data_dir: Path
) -> None:
    recorder = Recorder()
    _app_on_test_dir(client, recorder)

    for provider in PROVIDERS:
        r = client.post(f"/api/integrations/{provider}/sync")
        assert r.status_code >= 400  # no credentials for this instance
        r = client.post(f"/api/integrations/{provider}/disconnect")
        assert r.status_code == 200

    assert keyring_backend.unsuffixed_access() == []
    assert keyring_backend.production_untouched()
    # Nothing was sent to Google at all: no refresh, no revocation.
    assert recorder.requests == []
    assert not any(secret in recorder.bodies() for secret in PROD_SECRETS)


def test_refresh_and_revoke_use_only_the_test_instance_credentials(
    keyring_backend: InstrumentedKeyring, client: TestClient
) -> None:
    recorder = Recorder()
    _app_on_test_dir(client, recorder)
    namespace = client.app.state.credential_store._namespace
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    for provider in PROVIDERS:
        base = f"jarvis.{provider}.{namespace}"
        keyring_backend.items[(base, "access_token")] = "TEST-ACCESS"
        keyring_backend.items[(base, "refresh_token")] = "TEST-REFRESH"
        keyring_backend.items[(base, "access_token_expires_at")] = past
        keyring_backend.items[(base, "client_id")] = "test-client-id"
        keyring_backend.items[(base, "client_secret")] = "TEST-CLIENT-SECRET"

    from app import integration_service

    with client.app.state.session_factory() as db:
        for provider in PROVIDERS:
            token = integration_service.ensure_fresh_access_token(
                db, client.app.state.credential_store, client.app.state.integration_http_client, provider
            )
            assert token == "TEST-ACCESS-2"
    for provider in PROVIDERS:
        assert client.post(f"/api/integrations/{provider}/disconnect").status_code == 200

    token_calls = [r for r in recorder.requests if r.url.path.endswith("/token")]
    revoke_calls = [r for r in recorder.requests if r.url.path.endswith("/revoke")]
    assert len(token_calls) == 2 and len(revoke_calls) == 2
    assert all(b"TEST-REFRESH" in r.content for r in token_calls)
    assert all(b"TEST-ACCESS-2" in r.content for r in revoke_calls)
    assert not any(secret in recorder.bodies() for secret in PROD_SECRETS)
    assert keyring_backend.unsuffixed_access() == []
    assert keyring_backend.production_untouched()


def test_missing_credentials_do_not_leave_a_connected_status(
    keyring_backend: InstrumentedKeyring, client: TestClient
) -> None:
    recorder = Recorder()
    _app_on_test_dir(client, recorder)
    client.post("/api/integrations/google_calendar/sync")
    rows = {r["provider"]: r for r in client.get("/api/integrations").json()}
    assert rows["google_calendar"]["status"] == "error"
    assert "Reconnect" in rows["google_calendar"]["last_error"]


@pytest.mark.parametrize(
    "spelling",
    ["~/JarvisData", "~/JarvisData/", "~/jarvisdata", "~/JARVISDATA/", "~/JarvisData/../JarvisData"],
)
def test_spellings_of_the_default_folder_map_to_the_real_names(spelling: str) -> None:
    assert is_default_data_dir(Path(spelling))
    assert keychain_namespace_for(Path(spelling)) is None


def test_symlink_to_the_default_folder_is_the_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    (fake_home / "JarvisData").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    link = tmp_path / "link"
    link.symlink_to(fake_home / "JarvisData")
    assert keychain_namespace_for(link) is None
    assert keychain_namespace_for(tmp_path / "other") is not None


def test_relative_and_case_variant_test_dirs_share_one_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "Data").mkdir()
    monkeypatch.chdir(tmp_path)
    assert keychain_namespace_for(Path("Data")) == keychain_namespace_for(tmp_path / "Data")
    assert keychain_namespace_for(tmp_path / "Data/") == keychain_namespace_for(tmp_path / "data")


def test_environment_guard_selects_memory_store() -> None:
    assert os.environ.get("JARVIS_CREDENTIAL_STORE") == "memory"
    assert isinstance(build_credential_store(Path.home() / "JarvisData"), FakeCredentialStore)


def test_environment_guard_reaches_subprocesses() -> None:
    code = (
        "from pathlib import Path; from app.credential_store import build_credential_store, FakeCredentialStore; "
        "print(isinstance(build_credential_store(Path.home() / 'JarvisData'), FakeCredentialStore))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], check=True
    )
    assert out.stdout.strip() == "True"
