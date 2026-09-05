from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from app.archive_common import DATABASE_ARCHIVE_PATH
from app.config import Settings
from app.export_service import DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS, ExportError, cleanup_stale_export_temp_files, create_export
from app.migration_info import get_head_revision


def test_export_from_populated_installation(populated_settings: Settings) -> None:
    result = create_export(populated_settings)

    assert result.path.exists()
    assert result.filename.startswith("jarvis-export-")
    assert result.filename.endswith(".zip")
    assert result.size_bytes > 0


def test_export_contains_all_six_domains(populated_settings: Settings) -> None:
    result = create_export(populated_settings)

    with zipfile.ZipFile(result.path) as zf:
        zf.extractall(result.path.parent / "extracted")
    db_path = result.path.parent / "extracted" / DATABASE_ARCHIVE_PATH
    conn = sqlite3.connect(str(db_path))
    try:
        slugs = {row[0] for row in conn.execute("SELECT slug FROM domains").fetchall()}
    finally:
        conn.close()

    assert slugs == {"body", "mind", "people", "path", "build", "life"}


def test_export_while_database_open_stays_consistent(populated_settings: Settings) -> None:
    # Simulate the "app is running" case: hold an open connection to the
    # source database while exporting.
    live_conn = sqlite3.connect(str(populated_settings.database_path))
    try:
        live_conn.execute("SELECT COUNT(*) FROM messages")
        result = create_export(populated_settings)
    finally:
        live_conn.close()

    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert DATABASE_ARCHIVE_PATH in names


def test_manifest_contents(populated_settings: Settings) -> None:
    result = create_export(populated_settings)

    with zipfile.ZipFile(result.path) as zf:
        manifest = json.loads(zf.read("manifest.json"))

    assert manifest["export_format_version"] == "1.0"
    assert manifest["schema_revision"] == get_head_revision()
    assert manifest["secrets_included"] is False
    assert manifest["checksum_algorithm"] == "sha256"
    assert set(manifest["included_components"]) == {
        "database",
        "documents",
        "domain-summaries",
        "skills",
    }
    assert manifest["hermes_profile_export"]["included"] is False
    assert "created_at_utc" in manifest
    assert isinstance(manifest["files"], list) and len(manifest["files"]) >= 4


def test_manifest_has_no_absolute_home_path(populated_settings: Settings) -> None:
    result = create_export(populated_settings)

    with zipfile.ZipFile(result.path) as zf:
        manifest_text = zf.read("manifest.json").decode()
        names = zf.namelist()

    home = str(Path.home())
    assert home not in manifest_text
    for name in names:
        assert not name.startswith("/")
        assert home not in name


def test_export_excludes_env_and_secret_like_files(populated_settings: Settings) -> None:
    (populated_settings.configuration_dir).mkdir(parents=True, exist_ok=True)
    (populated_settings.configuration_dir / ".env").write_text("SECRET=shh\n")
    (populated_settings.configuration_dir / ".env.local").write_text("SECRET=shh\n")
    (populated_settings.configuration_dir / "safe.json").write_text("{}\n")

    result = create_export(populated_settings)

    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()

    assert not any(".env" in name for name in names)
    assert "configuration/safe.json" in names


def test_sha256_checksums_are_correct(populated_settings: Settings) -> None:
    import hashlib

    result = create_export(populated_settings)

    with zipfile.ZipFile(result.path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        for entry in manifest["files"]:
            data = zf.read(entry["path"])
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert len(data) == entry["size"]


def test_deterministic_inclusion_rules_skip_empty_payload_dirs(data_dir: Path) -> None:
    from tests.conftest import _prepare_schema

    settings = _prepare_schema(data_dir)
    from app.database import build_sessionmaker
    from app.database import build_engine as _build_engine
    from app.seed import seed_domains

    engine = _build_engine(settings.database_url)
    with build_sessionmaker(engine)() as session:
        seed_domains(session)
    engine.dispose()
    # documents/, domain-summaries/, skills/ are all empty here.

    result = create_export(settings)

    assert result.manifest["included_components"] == ["database"]


def test_export_fails_safely_on_inconsistent_database(populated_settings: Settings) -> None:
    # Corrupt the database file so PRAGMA integrity_check fails.
    with populated_settings.database_path.open("r+b") as handle:
        handle.seek(100)
        handle.write(b"\xff" * 64)

    with pytest.raises(ExportError):
        create_export(populated_settings)

    # No partial/incomplete export file should be left behind.
    leftover = list(populated_settings.exports_dir.glob("jarvis-export-*.zip"))
    assert leftover == []


# --- D85: stale export scratch-file cleanup -------------------------------


def _age_file(path: Path, seconds_old: float) -> None:
    stale_time = time.time() - seconds_old
    os.utime(path, (stale_time, stale_time))


class TestCleanupStaleExportTempFiles:
    def test_a_valid_stale_tmp_file_is_removed(self, populated_settings: Settings) -> None:
        stale = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.tmp-4242-1735732800000"
        stale.write_bytes(b"leftover partial zip bytes")
        _age_file(stale, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 1
        assert not stale.exists()

    def test_a_valid_stale_dbsnapshot_file_is_removed(self, populated_settings: Settings) -> None:
        stale = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.dbsnapshot-4242"
        stale.write_bytes(b"leftover raw sqlite snapshot bytes")
        _age_file(stale, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 1
        assert not stale.exists()

    def test_a_recent_file_matching_the_pattern_is_never_removed(self, populated_settings: Settings) -> None:
        # A genuinely in-progress export (or one that finished moments ago,
        # racing this sweep) must never be swept out from under itself.
        recent = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.tmp-4242-1735732800000"
        recent.write_bytes(b"in-progress zip bytes")
        # No _age_file call — mtime is "now".

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 0
        assert recent.exists()

    def test_an_unrelated_file_in_exports_dir_is_never_removed(self, populated_settings: Settings) -> None:
        unrelated_names = [
            "notes.txt",
            ".hidden-but-not-ours",
            ".jarvis-export-20250101-120000.zip.tmp",  # missing the required -<pid>-<millis> suffix
            "jarvis-export-20250101-120000.zip.tmp-4242-1735732800000",  # not dot-prefixed
        ]
        for name in unrelated_names:
            path = populated_settings.exports_dir / name
            path.write_bytes(b"unrelated content")
            _age_file(path, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 0
        for name in unrelated_names:
            assert (populated_settings.exports_dir / name).exists()

    def test_a_completed_export_is_never_removed_regardless_of_age(self, populated_settings: Settings) -> None:
        result = create_export(populated_settings)
        _age_file(result.path, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS * 10)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 0
        assert result.path.exists()

    def test_a_symlink_escaping_exports_dir_is_never_followed_or_removed(
        self, populated_settings: Settings, tmp_path: Path
    ) -> None:
        outside_target = tmp_path / "outside-target.txt"
        outside_target.write_bytes(b"must survive untouched")
        # `entry.stat()` follows symlinks (matching Path.stat()'s default),
        # so the age check sees the *target's* mtime — age it well past the
        # threshold. This isolates the parent-directory safety check as the
        # only thing that can still be preventing removal: without it, this
        # test would otherwise pass vacuously (skipped for being "too
        # young" rather than for escaping exports_dir) — confirmed by
        # deliberately removing the parent-directory check and re-running
        # this test, which failed for exactly that reason before this fix.
        _age_file(outside_target, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        malicious_link = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.tmp-1-1"
        malicious_link.symlink_to(outside_target)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 0
        assert malicious_link.exists()  # the link itself is untouched
        assert outside_target.exists()
        assert outside_target.read_bytes() == b"must survive untouched"

    def test_cleanup_of_a_populated_exports_dir_only_removes_the_matching_stale_files(
        self, populated_settings: Settings
    ) -> None:
        stale_tmp = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.tmp-1-1"
        stale_snapshot = populated_settings.exports_dir / ".jarvis-export-20250101-120000.zip.dbsnapshot-2"
        real_export = populated_settings.exports_dir / "jarvis-export-20250102-000000.zip"
        for f in (stale_tmp, stale_snapshot, real_export):
            f.write_bytes(b"x")
            _age_file(f, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        removed = cleanup_stale_export_temp_files(populated_settings)

        assert removed == 2
        assert not stale_tmp.exists()
        assert not stale_snapshot.exists()
        assert real_export.exists()

    def test_missing_exports_dir_is_a_safe_no_op(self, populated_settings: Settings) -> None:
        import shutil

        shutil.rmtree(populated_settings.exports_dir)
        assert cleanup_stale_export_temp_files(populated_settings) == 0

    def test_a_stale_file_is_actually_removed_by_a_real_app_startup(
        self, restart_client_factory
    ) -> None:
        """End-to-end version of the unit tests above: proves app.main's
        real lifespan actually calls this, not just the function in
        isolation (mirrors the same real-startup pattern used for
        action_service.expire_interrupted_executions in test_actions_api.py)."""
        from app.config import get_settings

        restart_client_factory()  # first startup — establishes the isolated JARVIS_DATA_DIR
        settings = get_settings()
        stale = settings.exports_dir / ".jarvis-export-20250101-120000.zip.tmp-1-1"
        stale.write_bytes(b"leftover")
        _age_file(stale, DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS + 60)

        restart_client_factory()  # a real second startup, running the real lifespan

        assert not stale.exists()
