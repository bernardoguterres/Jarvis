"""Local backups, using the same consistent-snapshot principle as exports.

Retention is a simple grandfather-father-son scheme with three independent
categories (daily/weekly/monthly), each pruned to its own target count. This
is a lightweight due-check invoked on application startup, not a scheduler —
see docs/ARCHITECTURE.md for why a heavier scheduler is deferred.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings

CATEGORIES = ("daily", "weekly", "monthly")
DUE_INTERVALS = {
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

# 'pre_delete' is a separate category, never created by the startup due-check
# and never subject to DUE_INTERVALS — it's only created explicitly, right
# before a permanent memory deletion (see app/memory_service.py), as a
# rollback safety net.
ALL_CATEGORIES = CATEGORIES + ("pre_delete",)
RETENTION_TARGETS = {"daily": 7, "weekly": 4, "monthly": 12, "pre_delete": 20}

_FILENAME_RE = re.compile(
    r"^jarvis-backup-(?P<category>daily|weekly|monthly|pre_delete)-(?P<ts>\d{8}-\d{6})\.sqlite$"
)


class BackupError(Exception):
    pass


@dataclass
class BackupResult:
    category: str
    filename: str
    path: Path
    created_at_utc: str
    size_bytes: int
    sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_database_consistent(db_path: Path) -> None:
    if not db_path.exists():
        raise BackupError(f"Database not found at {db_path.name}; nothing to back up.")
    conn = sqlite3.connect(str(db_path))
    try:
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        if not integrity_rows or integrity_rows[0][0] != "ok":
            raise BackupError(f"Refusing to back up: database integrity check failed: {integrity_rows}")
    finally:
        conn.close()


def _snapshot_sqlite(source_db_path: Path, dest_db_path: Path) -> None:
    """Consistent snapshot via SQLite's online backup API. Extracted as its
    own function so tests can simulate a corrupted/incomplete snapshot."""
    source_conn = sqlite3.connect(str(source_db_path))
    dest_conn = sqlite3.connect(str(dest_db_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()


def create_backup(settings: Settings, category: str = "daily") -> BackupResult:
    if category not in ALL_CATEGORIES:
        raise BackupError(f"Unknown backup category: {category!r}")

    settings.ensure_directories()
    _check_database_consistent(settings.database_path)

    category_dir = settings.backups_dir / category
    category_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime("%Y%m%d-%H%M%S")
    filename = f"jarvis-backup-{category}-{timestamp}.sqlite"
    final_path = category_dir / filename
    tmp_path = category_dir / f".{filename}.tmp-{os.getpid()}-{int(time.time() * 1000)}"

    try:
        _snapshot_sqlite(settings.database_path, tmp_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise BackupError("Backup snapshot failed; no backup file was left behind.")

    # Never treat an incomplete snapshot as successful.
    try:
        verify_conn = sqlite3.connect(str(tmp_path))
        try:
            rows = verify_conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"Backup snapshot is unreadable or corrupt: {exc}") from exc
        finally:
            verify_conn.close()

        if not rows or rows[0][0] != "ok":
            raise BackupError(f"Backup snapshot failed integrity check: {rows}")
    except BackupError:
        tmp_path.unlink(missing_ok=True)
        raise

    os.replace(tmp_path, final_path)
    checksum = _sha256_file(final_path)
    (category_dir / f"{filename}.sha256").write_text(checksum + "\n")

    _prune_category(settings, category)

    return BackupResult(
        category=category,
        filename=filename,
        path=final_path,
        created_at_utc=created_at.isoformat(),
        size_bytes=final_path.stat().st_size,
        sha256=checksum,
    )


def _list_category_backups(settings: Settings, category: str) -> list[tuple[str, Path]]:
    """Returns (timestamp, path) pairs for recognised backup files in one
    category directory, oldest first. Never follows symlinks and never
    touches files that don't match the exact expected naming pattern."""
    category_dir = settings.backups_dir / category
    if not category_dir.exists():
        return []

    results: list[tuple[str, Path]] = []
    for entry in category_dir.iterdir():
        if entry.is_symlink():
            continue
        if not entry.is_file():
            continue
        match = _FILENAME_RE.match(entry.name)
        if not match or match.group("category") != category:
            continue
        results.append((match.group("ts"), entry))

    results.sort(key=lambda pair: pair[0])
    return results


def _prune_category(settings: Settings, category: str) -> list[Path]:
    """Deletes the oldest recognised backups beyond the retention target for
    this category. Only ever deletes files matching the strict backup
    filename pattern inside the category's own directory; unknown files are
    always left alone."""
    target = RETENTION_TARGETS[category]
    backups = _list_category_backups(settings, category)
    excess = len(backups) - target
    if excess <= 0:
        return []

    removed: list[Path] = []
    for _, path in backups[:excess]:
        checksum_sidecar = path.parent / f"{path.name}.sha256"
        path.unlink(missing_ok=True)
        checksum_sidecar.unlink(missing_ok=True)
        removed.append(path)
    return removed


def get_latest_backup_info(settings: Settings) -> dict:
    """Latest backup per category, plus the single most recent overall."""
    per_category: dict[str, dict | None] = {}
    latest_overall: dict | None = None

    for category in CATEGORIES:
        backups = _list_category_backups(settings, category)
        if not backups:
            per_category[category] = None
            continue
        ts, path = backups[-1]
        info = {
            "category": category,
            "filename": path.name,
            "created_at_utc": _timestamp_to_iso(ts),
            "size_bytes": path.stat().st_size,
        }
        per_category[category] = info
        if latest_overall is None or ts > latest_overall["_ts"]:
            latest_overall = {**info, "_ts": ts}

    if latest_overall is not None:
        latest_overall = {k: v for k, v in latest_overall.items() if k != "_ts"}

    return {"latest": latest_overall, "by_category": per_category}


def _timestamp_to_iso(ts: str) -> str:
    dt = datetime.strptime(ts, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def run_due_backups(settings: Settings) -> list[BackupResult]:
    """Lightweight startup due-check: creates a backup for any category whose
    most recent backup is older than that category's interval (or missing
    entirely). Full recurring scheduling is deferred to a later phase."""
    if not settings.database_path.exists():
        return []

    created: list[BackupResult] = []
    now = datetime.now(timezone.utc)

    for category in CATEGORIES:
        backups = _list_category_backups(settings, category)
        is_due = True
        if backups:
            ts, _ = backups[-1]
            last_created = datetime.strptime(ts, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            is_due = (now - last_created) >= DUE_INTERVALS[category]

        if is_due:
            try:
                created.append(create_backup(settings, category=category))
            except BackupError:
                # Failure reporting is the caller's responsibility (e.g. logs);
                # a failed due-backup must never block application startup.
                continue

    return created
