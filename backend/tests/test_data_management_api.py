from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient


def test_data_dir_endpoint_returns_resolved_isolated_path(client: TestClient, data_dir) -> None:
    resp = client.get("/api/data-dir")
    assert resp.status_code == 200
    assert resp.json()["path"] == str(data_dir)


def test_export_endpoint_creates_export(client: TestClient) -> None:
    resp = client.post("/api/export")
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"].startswith("jarvis-export-")
    assert body["size_bytes"] > 0
    assert "database" in body["included_components"]


def test_list_exports_endpoint(client: TestClient) -> None:
    assert client.get("/api/exports").json() == []

    client.post("/api/export")
    resp = client.get("/api/exports")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["filename"].startswith("jarvis-export-")


def test_download_export_endpoint(client: TestClient) -> None:
    created = client.post("/api/export").json()
    filename = created["filename"]

    resp = client.get(f"/api/exports/{filename}/download")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "manifest.json" in zf.namelist()


def test_download_export_rejects_path_traversal(client: TestClient) -> None:
    client.post("/api/export")

    resp = client.get("/api/exports/..%2F..%2F..%2Fetc%2Fpasswd/download")
    assert resp.status_code == 404

    resp = client.get("/api/exports/not-a-real-export.zip/download")
    assert resp.status_code == 404


def test_download_export_rejects_unrecognised_filename(client: TestClient) -> None:
    resp = client.get("/api/exports/evil.zip/download")
    assert resp.status_code == 404

    resp = client.get("/api/exports/jarvis-export-99999999-999999.zip/download")
    assert resp.status_code == 404


def test_backup_endpoint(client: TestClient) -> None:
    resp = client.post("/api/backups")
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"] == "daily"
    assert body["sha256"]


def test_backup_endpoint_invalid_category(client: TestClient) -> None:
    resp = client.post("/api/backups", params={"category": "yearly"})
    assert resp.status_code == 422


def test_latest_backup_endpoint(client: TestClient) -> None:
    resp = client.get("/api/backups/latest")
    assert resp.status_code == 200
    assert resp.json()["latest"] is not None  # startup due-check already ran


def test_import_validate_endpoint_accepts_valid_archive(client: TestClient) -> None:
    created = client.post("/api/export").json()
    filename = created["filename"]
    archive_bytes = client.get(f"/api/exports/{filename}/download").content

    resp = client.post(
        "/api/imports/validate",
        files={"file": ("export.zip", archive_bytes, "application/zip")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["manifest"]["export_format_version"] == "1.0"


def test_import_validate_endpoint_rejects_garbage(client: TestClient) -> None:
    resp = client.post(
        "/api/imports/validate",
        files={"file": ("not-a-zip.zip", b"this is not a zip file", "application/zip")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert any("zip" in e.lower() for e in body["errors"])


def test_restore_endpoint_requires_confirm_when_target_has_data(client: TestClient) -> None:
    # The target (this same client's own data dir) already has real seeded
    # data (domains etc.) — restoring without confirm=true must be refused,
    # mirroring the CLI's own --confirm requirement exactly.
    created = client.post("/api/export").json()
    archive_bytes = client.get(f"/api/exports/{created['filename']}/download").content

    resp = client.post(
        "/api/restore",
        files={"file": ("export.zip", archive_bytes, "application/zip")},
    )

    assert resp.status_code == 409


def test_restore_endpoint_restores_over_the_live_database(client: TestClient) -> None:
    # This is the actual scenario the native app's "Restore from Jarvis
    # export" action performs: restoring an export back onto this exact
    # running process's own live database. It must succeed without
    # corrupting the process's ability to keep serving requests afterward
    # — the real regression test for disposing the shared engine's pooled
    # connections before the database file underneath it is replaced.
    created = client.post("/api/export").json()
    archive_bytes = client.get(f"/api/exports/{created['filename']}/download").content

    resp = client.post(
        "/api/restore",
        files={"file": ("export.zip", archive_bytes, "application/zip")},
        data={"confirm": "true"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["domains_restored"] == 6
    assert body["schema_revision_after"] is not None
    assert body["rollback_dir"] is not None

    # The same process must still be able to serve requests against the
    # (now-restored) database afterward — proves the engine handed live
    # requests transparently, rather than needing a process restart.
    health = client.get("/api/health")
    assert health.status_code == 200
    domains = client.get("/api/domains")
    assert domains.status_code == 200
    assert len(domains.json()) == 6


def test_restore_endpoint_forces_integrations_disconnected_and_schedules_disabled(
    client: TestClient,
) -> None:
    created = client.post("/api/export").json()
    archive_bytes = client.get(f"/api/exports/{created['filename']}/download").content

    resp = client.post(
        "/api/restore",
        files={"file": ("export.zip", archive_bytes, "application/zip")},
        data={"confirm": "true"},
    )

    assert resp.status_code == 200
    integrations = client.get("/api/integrations").json()
    assert all(item["status"] == "disconnected" for item in integrations)


def test_restore_endpoint_rejects_invalid_archive(client: TestClient) -> None:
    resp = client.post(
        "/api/restore",
        files={"file": ("not-a-zip.zip", b"garbage", "application/zip")},
        data={"confirm": "true"},
    )

    assert resp.status_code == 422
