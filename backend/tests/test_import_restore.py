from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.export_service import create_export
from app.import_service import RestoreError, ValidationError, restore_archive, validate_archive


def _export(populated_settings: Settings) -> Path:
    return create_export(populated_settings).path


def test_clean_directory_restore(populated_settings: Settings, tmp_path: Path) -> None:
    archive_path = _export(populated_settings)
    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))

    report = restore_archive(archive_path, target)

    assert report.domains_restored == 6
    assert report.conversations_restored == 2
    assert report.messages_restored == 2
    assert report.documents_restored == 1
    assert report.domain_summaries_restored == 1
    assert report.skills_restored == 1
    assert report.rollback_dir is None


def test_restore_preserves_domains_conversations_messages(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    restore_archive(archive_path, target)

    conn = sqlite3.connect(str(target.database_path))
    try:
        domains = {row[0] for row in conn.execute("SELECT slug FROM domains").fetchall()}
        assert domains == {"body", "mind", "people", "path", "build", "life"}

        titles = {row[0] for row in conn.execute("SELECT title FROM conversations").fetchall()}
        assert titles == {"Knee check-in", "Alpha checkpoint"}

        contents = {row[0] for row in conn.execute("SELECT content FROM messages").fetchall()}
        assert contents == {"Knee felt fine today.", "Shipped the tokenizer fix."}
    finally:
        conn.close()


def test_restore_preserves_uuids_and_timestamps(
    populated_settings: Settings, tmp_path: Path
) -> None:
    source_conn = sqlite3.connect(str(populated_settings.database_path))
    try:
        original = {
            row[0]: (row[1], row[2])
            for row in source_conn.execute("SELECT slug, id, created_at FROM domains").fetchall()
        }
    finally:
        source_conn.close()

    archive_path = _export(populated_settings)
    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    restore_archive(archive_path, target)

    target_conn = sqlite3.connect(str(target.database_path))
    try:
        restored = {
            row[0]: (row[1], row[2])
            for row in target_conn.execute("SELECT slug, id, created_at FROM domains").fetchall()
        }
    finally:
        target_conn.close()

    assert restored == original


def test_restore_preserves_documents_summaries_skills(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    restore_archive(archive_path, target)

    assert (target.documents_dir / "note.txt").read_text() == (
        populated_settings.documents_dir / "note.txt"
    ).read_text()
    assert (target.domain_summaries_dir / "body.md").exists()
    assert (target.skills_dir / "log-weight.md").exists()


def test_domain_isolation_preserved_after_restore(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    restore_archive(archive_path, target)

    conn = sqlite3.connect(str(target.database_path))
    try:
        row = conn.execute("SELECT id FROM domains WHERE slug = 'body'").fetchone()
        build_row = conn.execute("SELECT id FROM domains WHERE slug = 'build'").fetchone()
        body_id, build_id = row[0], build_row[0]

        body_convos = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE domain_id = ?", (body_id,)
        ).fetchone()[0]
        build_convos = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE domain_id = ?", (build_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    assert body_convos == 1
    assert build_convos == 1


# --- rejection cases -------------------------------------------------------


def _rewrite_zip_member(archive_path: Path, member: str, new_content: bytes) -> None:
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == member:
                data = new_content
            dst.writestr(info, data)
    shutil.move(str(tmp), str(archive_path))


def test_rejects_modified_payload(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    _rewrite_zip_member(archive_path, "documents/note.txt", b"tampered content")

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("Checksum mismatch" in e for e in result.errors)


def test_rejects_modified_checksum_manifest(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)

    with zipfile.ZipFile(archive_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    manifest["files"][0]["sha256"] = "0" * 64
    _rewrite_zip_member(archive_path, "manifest.json", json.dumps(manifest).encode())

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("Checksum mismatch" in e for e in result.errors)


def test_rejects_missing_required_file(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename == "documents/note.txt":
                continue
            dst.writestr(info, src.read(info.filename))
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("missing" in e.lower() for e in result.errors)


def test_rejects_undeclared_file(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("documents/sneaky.txt", "not declared in manifest")
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("undeclared" in e.lower() for e in result.errors)


def test_rejects_path_traversal(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("../../etc/evil.txt", "escape attempt")
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("traversal" in e.lower() for e in result.errors)


def test_rejects_absolute_archive_path(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("/etc/evil.txt", "absolute path attempt")
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("absolute" in e.lower() for e in result.errors)


def test_rejects_symlink_member(populated_settings: Settings) -> None:
    import stat

    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        link_info = zipfile.ZipInfo("documents/evil-link")
        link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        dst.writestr(link_info, "/etc/passwd")
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("symlink" in e.lower() for e in result.errors)


def test_rejects_duplicate_archive_member(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        # Duplicate one member under a differently-cased separator to trigger
        # the normalized-path duplicate check.
        dst.writestr("documents/note.txt", "duplicate")
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("duplicate" in e.lower() for e in result.errors)


def test_rejects_unsupported_future_export_version(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)
    with zipfile.ZipFile(archive_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    manifest["export_format_version"] = "99.0"
    _rewrite_zip_member(archive_path, "manifest.json", json.dumps(manifest).encode())

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("Unsupported export-format version" in e for e in result.errors)


def test_rejects_unsupported_future_schema_revision(populated_settings: Settings) -> None:
    archive_path = _export(populated_settings)

    # Extract, bump the archived DB's alembic_version to a bogus future
    # revision, and re-zip with a matching checksum so only the schema check
    # (not the checksum check) is exercised.
    with zipfile.ZipFile(archive_path) as zf:
        db_bytes = zf.read("database/jarvis.sqlite")
        manifest = json.loads(zf.read("manifest.json"))

    scratch_db = archive_path.parent / "scratch.sqlite"
    scratch_db.write_bytes(db_bytes)
    conn = sqlite3.connect(str(scratch_db))
    conn.execute("UPDATE alembic_version SET version_num = 'nonexistent-future-revision'")
    conn.commit()
    conn.close()
    new_db_bytes = scratch_db.read_bytes()
    scratch_db.unlink()

    import hashlib

    for entry in manifest["files"]:
        if entry["path"] == "database/jarvis.sqlite":
            entry["sha256"] = hashlib.sha256(new_db_bytes).hexdigest()
            entry["size"] = len(new_db_bytes)

    tmp = archive_path.with_suffix(".tmp.zip")
    with zipfile.ZipFile(archive_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.filename == "database/jarvis.sqlite":
                dst.writestr(info, new_db_bytes)
            elif info.filename == "manifest.json":
                dst.writestr(info, json.dumps(manifest).encode())
            else:
                dst.writestr(info, src.read(info.filename))
    shutil.move(str(tmp), str(archive_path))

    result = validate_archive(archive_path)

    assert not result.ok
    assert any("not supported" in e.lower() for e in result.errors)


# --- restore safety ----------------------------------------------------------


def test_refuses_to_overwrite_non_empty_target_without_confirm(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    target_dir = tmp_path / "install-b"
    target = Settings(jarvis_data_dir=str(target_dir))
    restore_archive(archive_path, target)  # first restore into clean target

    with pytest.raises(RestoreError):
        restore_archive(archive_path, target, confirm_overwrite=False)


def test_rollback_backup_created_before_confirmed_overwrite(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    target_dir = tmp_path / "install-b"
    target = Settings(jarvis_data_dir=str(target_dir))
    restore_archive(archive_path, target)

    report = restore_archive(archive_path, target, confirm_overwrite=True)

    assert report.rollback_dir is not None
    assert report.rollback_dir.exists()
    assert (report.rollback_dir / "database" / "jarvis.sqlite").exists()


def test_existing_installation_preserved_after_simulated_failed_restore(
    populated_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive_path = _export(populated_settings)
    target_dir = tmp_path / "install-b"
    target = Settings(jarvis_data_dir=str(target_dir))
    restore_archive(archive_path, target)

    original_db_bytes = target.database_path.read_bytes()

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure during restore")

    monkeypatch.setattr("app.import_service.upgrade_database_to_head", _boom)

    with pytest.raises(RestoreError):
        restore_archive(archive_path, target, confirm_overwrite=True)

    assert target.database_path.read_bytes() == original_db_bytes


def test_invalid_archive_raises_validation_error_on_restore(
    populated_settings: Settings, tmp_path: Path
) -> None:
    archive_path = _export(populated_settings)
    _rewrite_zip_member(archive_path, "documents/note.txt", b"tampered")

    target = Settings(jarvis_data_dir=str(tmp_path / "install-b"))
    with pytest.raises(ValidationError):
        restore_archive(archive_path, target)

    assert not (target.data_dir / "database" / "jarvis.sqlite").exists()
