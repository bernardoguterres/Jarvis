from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.backup_service import (
    BackupError,
    CATEGORIES,
    RETENTION_TARGETS,
    _FILENAME_RE,
    create_backup,
    get_latest_backup_info,
    run_due_backups,
)
from app.config import Settings


def test_backup_creation(populated_settings: Settings) -> None:
    result = create_backup(populated_settings, category="daily")

    assert result.path.exists()
    assert result.category == "daily"
    assert result.sha256
    sidecar = result.path.parent / f"{result.filename}.sha256"
    assert sidecar.exists()
    assert sidecar.read_text().strip() == result.sha256


def test_backup_is_a_valid_consistent_snapshot(populated_settings: Settings) -> None:
    result = create_backup(populated_settings)

    conn = sqlite3.connect(str(result.path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        assert rows[0][0] == "ok"
        domains = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
        assert domains == 6
    finally:
        conn.close()


def test_latest_backup_info(populated_settings: Settings) -> None:
    assert get_latest_backup_info(populated_settings)["latest"] is None

    create_backup(populated_settings, category="daily")
    info = get_latest_backup_info(populated_settings)

    assert info["latest"]["category"] == "daily"
    assert info["by_category"]["daily"] is not None
    assert info["by_category"]["weekly"] is None


def test_backup_fails_on_missing_database(data_dir: Path) -> None:
    settings = Settings(jarvis_data_dir=str(data_dir))
    settings.ensure_directories()

    with pytest.raises(BackupError):
        create_backup(settings)


def test_retention_pruning_boundaries(populated_settings: Settings) -> None:
    category = "daily"
    target = RETENTION_TARGETS[category]

    category_dir = populated_settings.backups_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)

    # Seed (target + 3) fake, already-old backup files directly on disk so we
    # don't need to wait real time between creations.
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    fake_paths = []
    for i in range(target + 3):
        ts = (base_time + timedelta(hours=i)).strftime("%Y%m%d-%H%M%S")
        name = f"jarvis-backup-{category}-{ts}.sqlite"
        path = category_dir / name
        path.write_bytes(b"fake-sqlite-bytes")
        (category_dir / f"{name}.sha256").write_text("deadbeef\n")
        fake_paths.append(path)

    # A real backup call triggers pruning after it succeeds.
    create_backup(populated_settings, category=category)

    remaining = sorted(p.name for p in category_dir.glob("jarvis-backup-*.sqlite"))
    assert len(remaining) == target

    # The newest fake files plus the just-created real one should survive;
    # the oldest ones should have been pruned.
    assert len(remaining) == RETENTION_TARGETS[category]


def test_unknown_files_never_pruned(populated_settings: Settings) -> None:
    category_dir = populated_settings.backups_dir / "daily"
    category_dir.mkdir(parents=True, exist_ok=True)

    unrelated_file = category_dir / "not-a-jarvis-backup.txt"
    unrelated_file.write_text("please don't delete me")

    # Create far more than the retention target so pruning definitely runs.
    base_time = datetime.now(timezone.utc) - timedelta(days=60)
    for i in range(RETENTION_TARGETS["daily"] + 10):
        ts = (base_time + timedelta(hours=i)).strftime("%Y%m%d-%H%M%S")
        name = f"jarvis-backup-daily-{ts}.sqlite"
        (category_dir / name).write_bytes(b"fake")

    create_backup(populated_settings, category="daily")

    assert unrelated_file.exists()


def test_prune_never_follows_symlinks(populated_settings: Settings, tmp_path: Path) -> None:
    category_dir = populated_settings.backups_dir / "daily"
    category_dir.mkdir(parents=True, exist_ok=True)

    real_target = tmp_path / "outside-backups-dir.txt"
    real_target.write_text("should never be touched")
    symlink_path = category_dir / "jarvis-backup-daily-20200101-000000.sqlite"
    symlink_path.symlink_to(real_target)

    create_backup(populated_settings, category="daily")

    assert real_target.exists()
    assert real_target.read_text() == "should never be touched"


def test_failed_backup_never_treated_as_successful(
    populated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import backup_service

    def _corrupting_snapshot(source_db_path, dest_db_path):
        backup_service._snapshot_sqlite(source_db_path, dest_db_path)
        # Truncate the snapshot so it fails PRAGMA integrity_check.
        with open(dest_db_path, "r+b") as handle:
            handle.truncate(16)

    monkeypatch.setattr(backup_service, "_snapshot_sqlite", _corrupting_snapshot)

    with pytest.raises(backup_service.BackupError):
        create_backup(populated_settings, category="daily")

    leftover_tmp = list((populated_settings.backups_dir / "daily").glob(".jarvis-backup-*.tmp-*"))
    assert leftover_tmp == []
    leftover_final = list((populated_settings.backups_dir / "daily").glob("jarvis-backup-*.sqlite"))
    assert leftover_final == []


def test_run_due_backups_creates_missing_categories(populated_settings: Settings) -> None:
    created = run_due_backups(populated_settings)

    created_categories = {b.category for b in created}
    assert created_categories == set(CATEGORIES)


def test_run_due_backups_skips_recent_categories(populated_settings: Settings) -> None:
    run_due_backups(populated_settings)
    second_pass = run_due_backups(populated_settings)

    assert second_pass == []


def test_backup_filename_pattern_matches_expected_format() -> None:
    assert _FILENAME_RE.match("jarvis-backup-daily-20260101-120000.sqlite")
    assert not _FILENAME_RE.match("not-a-backup.sqlite")
