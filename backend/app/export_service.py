"""Builds a portable, versioned ZIP export of JARVIS_DATA_DIR.

Design notes (see docs/ARCHITECTURE.md and docs/DECISIONS.md for the full
rationale):

* The SQLite database is never copied with a plain filesystem copy. It is
  snapshotted with sqlite3's online backup API, which is safe to use while
  the source database is open and being written to.
* The archive is built in a temporary file inside exports/ and atomically
  renamed into place, so a crash or interruption never leaves a partial file
  with a "finished" name.
* A simple exclusive-lock file prevents two exports from running at once.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.archive_common import (
    APP_VERSION,
    DATABASE_ARCHIVE_PATH,
    EXPORT_FORMAT_VERSION,
    HERMES_PROFILE_ARCHIVE_DIR,
    HERMES_PROFILE_ARCHIVE_PATH,
    PAYLOAD_DIRS,
    is_excluded_name,
    platform_info,
)
from app.config import Settings
from app.hermes_profile_export import attempt_hermes_profile_export
from app.migration_info import read_db_revision


class ExportError(Exception):
    pass


class ExportInProgressError(ExportError):
    pass


@dataclass
class ExportResult:
    filename: str
    path: Path
    created_at_utc: str
    size_bytes: int
    manifest: dict = field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_database_consistent(db_path: Path) -> None:
    if not db_path.exists():
        raise ExportError(f"Database not found at {db_path.name}; nothing to export.")

    conn = sqlite3.connect(str(db_path))
    try:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as exc:
            raise ExportError(f"Refusing to export: database is unreadable or corrupt: {exc}") from exc

        if fk_violations:
            raise ExportError(
                f"Refusing to export: {len(fk_violations)} foreign-key violation(s) found."
            )
        if not integrity_rows or integrity_rows[0][0] != "ok":
            raise ExportError(f"Refusing to export: database integrity check failed: {integrity_rows}")
    finally:
        conn.close()


def _snapshot_sqlite(source_db_path: Path, dest_db_path: Path) -> None:
    """Consistent snapshot via SQLite's online backup API (safe while the
    source database is open and in use)."""
    dest_db_path.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(str(source_db_path))
    dest_conn = sqlite3.connect(str(dest_db_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()


def _collect_payload_files(source_dir: Path) -> list[tuple[str, Path]]:
    """Returns (archive_relative_path, absolute_source_path) pairs for every
    regular file under source_dir, skipping excluded names and symlinks."""
    results: list[tuple[str, Path]] = []
    if not source_dir.exists():
        return results

    for root, dirnames, filenames in os.walk(source_dir, followlinks=False):
        root_path = Path(root)
        dirnames[:] = [d for d in dirnames if not is_excluded_name(d)]
        for filename in sorted(filenames):
            if is_excluded_name(filename):
                continue
            file_path = root_path / filename
            if file_path.is_symlink():
                continue
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(source_dir.parent)
            archive_path = relative.as_posix()
            results.append((archive_path, file_path))

    return results


class _ExportLock:
    """A simple exclusive-lock file under exports/ so two exports never run
    at once. Uses flock, so a crashed process's lock is released by the OS."""

    def __init__(self, exports_dir: Path) -> None:
        self._lock_path = exports_dir / ".export.lock"
        self._fd: int | None = None

    def __enter__(self) -> "_ExportLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise ExportInProgressError(
                    "An export is already in progress. Try again shortly."
                ) from exc
            raise
        self._fd = fd
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


# Matches exactly the two filenames create_export() itself generates for a
# single attempt — nothing else. Deliberately precise (not a broad ".tmp-*"
# glob) so this can never match a real completed export (never dot-prefixed)
# or an unrelated file a user might have placed in exports_dir.
_STALE_EXPORT_TEMP_FILE = re.compile(
    r"^\.jarvis-export-\d{8}-\d{6}\.zip\.(?:tmp|dbsnapshot)-\d+(?:-\d+)?$"
)

# An export completes in well under a second even at a full multi-year
# personal-scale dataset (see docs/DECISIONS.md D85's scale benchmarks) —
# this threshold exists only to guarantee a genuinely in-progress export
# (a slow disk, a large Hermes profile export) is never mistaken for a
# stale one, not because exports are expected to take anywhere near this
# long.
DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS = 3600


def cleanup_stale_export_temp_files(
    settings: Settings, *, max_age_seconds: int = DEFAULT_STALE_EXPORT_TEMP_MAX_AGE_SECONDS
) -> int:
    """Removes only Jarvis's own leftover export scratch files — the
    ``.tmp-*`` (in-progress archive) and ``.dbsnapshot-*`` (raw SQLite
    snapshot) files `create_export` writes directly into `exports_dir`
    before atomically renaming the finished archive into place. A process
    killed mid-export (crash, `kill -9`, power loss) skips the `finally`
    block that would normally delete the dbsnapshot file and never reaches
    the `os.replace()` that would consume the .tmp file, so either can be
    left behind indefinitely with no other code path ever revisiting them —
    pure disk-hygiene, never a correctness or security issue (a completed,
    valid export is never named this way, and nothing reads these files
    back), but capable of accumulating slowly on a machine that stays on
    for a long time. Called once at backend startup; never blocks it.

    Safety, by construction:
    * Only ever lists `settings.exports_dir` itself (`Path.iterdir()`, not
      `os.walk`/`glob`/`rglob`) — never recurses, never touches any other
      directory, and no path segment is ever taken from outside this call.
    * Every candidate name must match `_STALE_EXPORT_TEMP_FILE` exactly —
      the precise pattern this module itself generates, not a broad glob —
      so a real completed export (`jarvis-export-*.zip`, never dot-prefixed)
      or any unrelated file a user placed in `exports_dir` is structurally
      unmatchable and always left untouched.
    * Each candidate's resolved parent must still be `exports_dir` resolved
      (`Path.resolve()` on both sides) before it is ever unlinked — defeats
      a symlink placed inside `exports_dir` that points elsewhere; nothing
      outside `exports_dir` is ever deleted even if such a link matched the
      name pattern (which, per the point above, it structurally cannot).
    * Age is judged by the file's own `st_mtime` (last content write), not
      a fixed "creation" timestamp SQLite/zip files don't reliably carry —
      a file younger than `max_age_seconds` is always left alone, so a
      genuinely in-progress export can never be removed out from under
      itself regardless of how slow that particular run is.
    * Any single file's stat/unlink failure (e.g. a permissions error, or
      the file disappearing between listing and unlinking) is caught and
      skipped — never allowed to abort the rest of the sweep or propagate
      to the caller.
    """
    exports_dir = settings.exports_dir
    if not exports_dir.is_dir():
        return 0

    resolved_exports_dir = exports_dir.resolve()
    now = time.time()
    removed = 0

    for entry in exports_dir.iterdir():
        if not _STALE_EXPORT_TEMP_FILE.match(entry.name):
            continue
        try:
            if entry.is_dir():
                continue
            resolved_entry = entry.resolve()
            if resolved_entry.parent != resolved_exports_dir:
                continue  # a symlink pointing outside exports_dir — never followed
            stat_result = entry.stat()
            age_seconds = now - stat_result.st_mtime
            if age_seconds < max_age_seconds:
                continue  # too young to be confidently "stale" rather than in-progress
            entry.unlink()
            removed += 1
        except OSError:
            continue

    return removed


def create_export(settings: Settings) -> ExportResult:
    settings.ensure_directories()
    _check_database_consistent(settings.database_path)

    with _ExportLock(settings.exports_dir):
        created_at = datetime.now(timezone.utc)
        timestamp = created_at.strftime("%Y%m%d-%H%M%S")
        filename = f"jarvis-export-{timestamp}.zip"
        final_path = settings.exports_dir / filename
        tmp_path = settings.exports_dir / f".{filename}.tmp-{os.getpid()}-{int(time.time() * 1000)}"

        schema_revision = read_db_revision(settings.database_path)

        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            # 1. Consistent database snapshot into a scratch file, then into the zip.
            # The checksum is computed from this scratch file's bytes, which are
            # exactly what gets stored (ZIP_DEFLATED is a lossless transform, so
            # the extracted member's bytes will match this file's bytes exactly).
            db_snapshot_path = tmp_path.parent / f".{filename}.dbsnapshot-{os.getpid()}"
            _snapshot_sqlite(settings.database_path, db_snapshot_path)
            try:
                db_sha256 = _sha256_file(db_snapshot_path)
                db_size = db_snapshot_path.stat().st_size
                archive.write(db_snapshot_path, DATABASE_ARCHIVE_PATH)
            finally:
                db_snapshot_path.unlink(missing_ok=True)

            files_manifest: list[dict] = [
                {"path": DATABASE_ARCHIVE_PATH, "sha256": db_sha256, "size": db_size}
            ]

            included_components = ["database"]

            # 2. Optional payload directories.
            for payload_dir in PAYLOAD_DIRS:
                source_dir = settings.data_dir / payload_dir
                pairs = _collect_payload_files(source_dir)
                if pairs:
                    included_components.append(payload_dir)
                for archive_path, source_path in pairs:
                    archive.write(source_path, archive_path)
                    files_manifest.append(
                        {
                            "path": archive_path,
                            "sha256": _sha256_file(source_path),
                            "size": source_path.stat().st_size,
                        }
                    )

            # 3. Optional Hermes profile export (Phase 3+). Always optional:
            # if the hermes CLI or the named profile isn't present, the main
            # Jarvis export proceeds without it.
            hermes_profile_manifest: dict = {
                "archive_path": HERMES_PROFILE_ARCHIVE_PATH,
                "included": False,
                "profile_name": settings.hermes_profile_name,
                "reason": "Hermes is not installed or the profile was not found.",
            }

            with tempfile.TemporaryDirectory(prefix="jarvis-hermes-export-") as hermes_tmp_dir:
                attempt = attempt_hermes_profile_export(
                    settings.hermes_profile_name,
                    settings.hermes_cli_command,
                    Path(hermes_tmp_dir),
                )
                if attempt.path is not None:
                    hermes_archive_path = (
                        f"{HERMES_PROFILE_ARCHIVE_DIR}/{settings.hermes_profile_name}.tar.gz"
                    )
                    hermes_sha256 = _sha256_file(attempt.path)
                    hermes_size = attempt.path.stat().st_size
                    archive.write(attempt.path, hermes_archive_path)
                    files_manifest.append(
                        {"path": hermes_archive_path, "sha256": hermes_sha256, "size": hermes_size}
                    )
                    included_components.append("hermes_profile")
                    hermes_profile_manifest = {
                        "archive_path": hermes_archive_path,
                        "included": True,
                        "profile_name": settings.hermes_profile_name,
                        "note": (
                            "No model credential (API key or OAuth token) is included, "
                            "regardless of which provider is configured. Re-establish it "
                            "via 'jarvis setup model' after restoring on a new machine."
                        ),
                    }
                elif attempt.skipped_reason is not None:
                    hermes_profile_manifest["reason"] = attempt.skipped_reason

            manifest = {
                "export_format_version": EXPORT_FORMAT_VERSION,
                "app_version": APP_VERSION,
                "schema_revision": schema_revision,
                "created_at_utc": created_at.isoformat(),
                "platform": platform_info(),
                "included_components": included_components,
                "excluded_components": {
                    "backups": "local-only, not part of a portable export",
                    "exports": "local-only, not part of a portable export",
                },
                "hermes_profile_export": hermes_profile_manifest,
                "secrets_included": False,
                "checksum_algorithm": "sha256",
                "files": files_manifest,
            }

            archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

        # Atomic publish: rename only after the archive is fully written and closed.
        os.replace(tmp_path, final_path)

    size_bytes = final_path.stat().st_size
    return ExportResult(
        filename=filename,
        path=final_path,
        created_at_utc=manifest["created_at_utc"],
        size_bytes=size_bytes,
        manifest=manifest,
    )
