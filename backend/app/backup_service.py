"""Local backups, using the same consistent-snapshot principle as exports.

Retention is a simple grandfather-father-son scheme with three independent
categories (daily/weekly/monthly), each pruned to its own target count.
The due-check runs at startup and again from the background scheduler
while the backend stays up (app/scheduler_runtime.py), so a Jarvis that is
left running for weeks still gets its daily backups.

Every backup, and every restore, takes an exclusive file lock in the
backups directory, so a scheduled backup, a manual one, a CLI one and a
restore can never overlap, even across processes.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings

logger = logging.getLogger("jarvis.backups")

CATEGORIES = ("daily", "weekly", "monthly")
DUE_INTERVALS = {
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

# 'pre_delete' is a separate category, never created by the startup due-check
# and never subject to DUE_INTERVALS. It's only created explicitly, right
# before a permanent memory deletion (see app/memory_service.py), as a
# rollback safety net.
# 'pre_migration' is likewise explicit-only: taken right before a schema
# upgrade changes an existing database (see backup_before_migration).
ALL_CATEGORIES = CATEGORIES + ("pre_delete", "pre_migration")
RETENTION_TARGETS = {"daily": 7, "weekly": 4, "monthly": 12, "pre_delete": 20, "pre_migration": 10}

# A daily backup older than this is reported as overdue. Slightly longer
# than the 24h interval so a backup taken a few minutes late is not flagged.
OVERDUE_AFTER = timedelta(hours=26)

_FILENAME_RE = re.compile(
    r"^jarvis-backup-(?P<category>daily|weekly|monthly|pre_delete|pre_migration)-(?P<ts>\d{8}-\d{6})\.sqlite$"
)
_LOCK_NAME = ".backup.lock"
_STATUS_NAME = ".backup-status.json"


class BackupError(Exception):
    pass


class BackupBusyError(BackupError):
    pass


@contextmanager
def backup_lock(settings: Settings, *, blocking: bool = True):
    """Exclusive lock shared by every backup and restore, in any process.
    Raises BackupBusyError when non-blocking and already held."""
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(settings.backups_dir / _LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as exc:
            raise BackupBusyError("Another backup or restore is in progress.") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _read_status(settings: Settings) -> dict:
    try:
        return json.loads((settings.backups_dir / _STATUS_NAME).read_text())
    except (OSError, ValueError):
        return {}


def _write_status(settings: Settings, **fields) -> None:
    status = _read_status(settings)
    status.update(fields)
    path = settings.backups_dir / _STATUS_NAME
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(status))
        os.replace(tmp, path)
    except OSError:
        logger.warning("Could not record backup status.")


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
    with backup_lock(settings):
        return _create_backup_locked(settings, category)


def _create_backup_locked(settings: Settings, category: str) -> BackupResult:
    """Caller must hold backup_lock."""
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

    status = _read_status(settings)
    latest_daily = per_category.get("daily")
    overdue = settings.database_path.exists() and (
        latest_daily is None
        or datetime.now(timezone.utc) - datetime.fromisoformat(latest_daily["created_at_utc"]) > OVERDUE_AFTER
    )
    return {
        "latest": latest_overall,
        "by_category": per_category,
        "last_attempt_at_utc": status.get("last_attempt_at_utc"),
        "last_error": status.get("last_error"),
        "last_error_at_utc": status.get("last_error_at_utc"),
        "overdue": bool(overdue),
    }


def _timestamp_to_iso(ts: str) -> str:
    dt = datetime.strptime(ts, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def run_due_backups(settings: Settings) -> list[BackupResult]:
    """Creates a backup for any category whose most recent backup is older
    than that category's interval (or missing entirely). Called at startup
    and periodically by the scheduler. If another backup or a restore holds
    the lock, this run is skipped and the next check tries again. A failure
    is logged and recorded so Data Management can show it; it never raises."""
    if not settings.database_path.exists():
        return []
    try:
        with backup_lock(settings, blocking=False):
            return _run_due_backups_locked(settings)
    except BackupBusyError:
        logger.info("Backup due-check skipped: another backup or restore is in progress.")
        return []


def _run_due_backups_locked(settings: Settings) -> list[BackupResult]:
    created: list[BackupResult] = []
    errors: list[str] = []
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
                created.append(_create_backup_locked(settings, category))
            except Exception as exc:
                logger.error("Scheduled %s backup failed: %s", category, exc)
                errors.append(f"{category} backup failed: {exc}")

    if created or errors:
        attempted_at = now.isoformat()
        if errors:
            _write_status(
                settings,
                last_attempt_at_utc=attempted_at,
                last_error="; ".join(errors)[:300],
                last_error_at_utc=attempted_at,
            )
        else:
            _write_status(settings, last_attempt_at_utc=attempted_at, last_error=None, last_error_at_utc=None)
    return created


def backup_before_migration(settings: Settings) -> BackupResult | None:
    """Takes a verified snapshot of an existing database before a schema
    upgrade changes it. Returns None when there is nothing to protect (no
    database yet, a brand-new unstamped file, or already at head). Raises
    BackupError if the snapshot fails, so the caller can refuse to migrate
    personal data without a way back."""
    from app.migration_info import get_head_revision, read_db_revision

    if not settings.database_path.exists():
        return None
    current = read_db_revision(settings.database_path)
    if current is None or current == get_head_revision():
        return None
    result = create_backup(settings, category="pre_migration")
    logger.info("Pre-migration backup %s taken (schema %s).", result.filename, current)
    return result
