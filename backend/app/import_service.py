"""Validates and restores a Jarvis export archive.

Validation always happens against a freshly created temporary directory —
an untrusted archive is never extracted directly into JARVIS_DATA_DIR (see
docs/ARCHITECTURE.md). Restoration is a separate, explicit step that only
proceeds once validation has fully passed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.archive_common import (
    DATABASE_ARCHIVE_PATH,
    MANIFEST_FILENAME,
    MAX_ARCHIVE_MEMBERS,
    MAX_TOTAL_UNCOMPRESSED_BYTES,
    SUPPORTED_EXPORT_FORMAT_VERSIONS,
    has_parent_traversal,
    is_absolute_archive_path,
    normalized_archive_path,
    zipinfo_is_symlink_or_special,
)
from app.config import Settings
from app.hermes_profile_export import find_secret_members
from app.migration_info import (
    get_head_revision,
    is_known_revision,
    read_db_revision,
    upgrade_database_to_head,
)

EXPECTED_DOMAIN_SLUGS = {"body", "mind", "people", "path", "build", "life"}


class ValidationError(Exception):
    pass


class RestoreError(Exception):
    pass


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    manifest: dict | None = None
    extracted_dir: Path | None = None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _structural_check(zf: zipfile.ZipFile) -> list[str]:
    """Cheap, allocation-free checks on ZIP member metadata before anything
    is extracted to disk."""
    errors: list[str] = []
    infos = zf.infolist()

    if len(infos) > MAX_ARCHIVE_MEMBERS:
        errors.append(
            f"Archive has {len(infos)} entries, exceeding the maximum of {MAX_ARCHIVE_MEMBERS}."
        )

    total_uncompressed = sum(info.file_size for info in infos)
    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
        errors.append(
            f"Archive's uncompressed size ({total_uncompressed} bytes) exceeds the "
            f"maximum of {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes."
        )

    seen_normalized: set[str] = set()
    for info in infos:
        name = info.filename

        if is_absolute_archive_path(name):
            errors.append(f"Archive member has an absolute path: {name!r}")
            continue

        if has_parent_traversal(name):
            errors.append(f"Archive member has parent-directory traversal: {name!r}")
            continue

        if zipinfo_is_symlink_or_special(info):
            errors.append(f"Archive member is a symlink or special file: {name!r}")
            continue

        normalized = normalized_archive_path(name)
        if normalized in seen_normalized:
            errors.append(f"Archive has a duplicate member: {name!r}")
        seen_normalized.add(normalized)

    return errors


def _extract_safely(zf: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extracts every member, re-checking the resolved path stays inside
    dest_dir even after the structural checks above (defense in depth)."""
    dest_root = dest_dir.resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        target_path = (dest_dir / info.filename).resolve()
        if not str(target_path).startswith(str(dest_root) + "/") and target_path != dest_root:
            raise ValidationError(f"Refusing to extract unsafe path: {info.filename!r}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as source, open(target_path, "wb") as dest:
            shutil.copyfileobj(source, dest)


def _manifest_schema_errors(manifest: dict) -> list[str]:
    errors: list[str] = []
    required_keys = {
        "export_format_version",
        "app_version",
        "schema_revision",
        "created_at_utc",
        "platform",
        "included_components",
        "excluded_components",
        "hermes_profile_export",
        "secrets_included",
        "checksum_algorithm",
        "files",
    }
    missing = required_keys - manifest.keys()
    if missing:
        errors.append(f"Manifest is missing required keys: {sorted(missing)}")
        return errors

    if manifest["export_format_version"] not in SUPPORTED_EXPORT_FORMAT_VERSIONS:
        errors.append(
            f"Unsupported export-format version: {manifest['export_format_version']!r}"
        )

    if manifest["checksum_algorithm"] != "sha256":
        errors.append(f"Unsupported checksum algorithm: {manifest['checksum_algorithm']!r}")

    if manifest["secrets_included"] is not False:
        errors.append("Archive declares secrets_included=true; refusing to restore credentials.")

    if not isinstance(manifest["files"], list) or not manifest["files"]:
        errors.append("Manifest 'files' list is missing or empty.")

    return errors


def validate_archive(archive_path: Path) -> ValidationResult:
    if not zipfile.is_zipfile(archive_path):
        return ValidationResult(ok=False, errors=["Not a valid ZIP file."])

    errors: list[str] = []

    with zipfile.ZipFile(archive_path) as zf:
        errors.extend(_structural_check(zf))
        if errors:
            return ValidationResult(ok=False, errors=errors)

        names = {info.filename for info in zf.infolist() if not info.is_dir()}
        if MANIFEST_FILENAME not in names:
            return ValidationResult(ok=False, errors=["Archive is missing manifest.json."])

        extracted_dir = Path(tempfile.mkdtemp(prefix="jarvis-import-"))
        _extract_safely(zf, extracted_dir)

    manifest_path = extracted_dir / MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as exc:
        shutil.rmtree(extracted_dir, ignore_errors=True)
        return ValidationResult(ok=False, errors=[f"manifest.json is not valid JSON: {exc}"])

    schema_errors = _manifest_schema_errors(manifest)
    if schema_errors:
        shutil.rmtree(extracted_dir, ignore_errors=True)
        return ValidationResult(ok=False, errors=schema_errors, manifest=manifest)

    # Checksums: every declared file must exist and match exactly.
    declared_paths = {entry["path"] for entry in manifest["files"]}
    for entry in manifest["files"]:
        file_path = extracted_dir / entry["path"]
        if not file_path.is_file():
            errors.append(f"Declared file missing from archive: {entry['path']!r}")
            continue
        actual_sha256 = _sha256_file(file_path)
        if actual_sha256 != entry["sha256"]:
            errors.append(f"Checksum mismatch for {entry['path']!r}: archive has been modified.")

    # Undeclared files: every extracted file must be manifest.json or a
    # declared payload file.
    for file_path in extracted_dir.rglob("*"):
        if file_path.is_dir():
            continue
        relative = file_path.relative_to(extracted_dir).as_posix()
        if relative == MANIFEST_FILENAME:
            continue
        if relative not in declared_paths:
            errors.append(f"Archive contains an undeclared file: {relative!r}")

    if DATABASE_ARCHIVE_PATH not in declared_paths:
        errors.append("Archive is missing the required database file.")

    hermes_export = manifest.get("hermes_profile_export") or {}
    if hermes_export.get("included"):
        hermes_archive_path = extracted_dir / hermes_export["archive_path"]
        if not hermes_archive_path.is_file():
            errors.append("Manifest declares an included Hermes profile export, but it is missing.")
        else:
            secret_members = find_secret_members(hermes_archive_path)
            if secret_members:
                errors.append(
                    "Rejecting archive: the included Hermes profile export contains "
                    f"secret file(s) that must never be present: {secret_members}"
                )

    if errors:
        shutil.rmtree(extracted_dir, ignore_errors=True)
        return ValidationResult(ok=False, errors=errors, manifest=manifest)

    # Database-level checks.
    db_path = extracted_dir / DATABASE_ARCHIVE_PATH
    db_errors, domain_slugs = _validate_database(db_path)
    errors.extend(db_errors)

    missing_domains = EXPECTED_DOMAIN_SLUGS - domain_slugs
    if missing_domains:
        errors.append(f"Archive database is missing required domains: {sorted(missing_domains)}")

    if errors:
        shutil.rmtree(extracted_dir, ignore_errors=True)
        return ValidationResult(ok=False, errors=errors, manifest=manifest)

    return ValidationResult(ok=True, errors=[], manifest=manifest, extracted_dir=extracted_dir)


def _validate_database(db_path: Path) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    domain_slugs: set[str] = set()

    if not db_path.exists():
        return (["Database file missing."], domain_slugs)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        if not integrity_rows or integrity_rows[0][0] != "ok":
            errors.append(f"Archived database failed integrity check: {integrity_rows}")

        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            errors.append(f"Archived database has {len(fk_violations)} foreign-key violation(s).")

        revision = read_db_revision(db_path)
        if revision is None:
            errors.append("Archived database has no schema revision (unmigrated).")
        elif not is_known_revision(revision):
            errors.append(
                f"Archived database's schema revision {revision!r} is not supported by "
                f"this version of Jarvis (known head: {get_head_revision()!r}). It may be "
                "from a newer, unsupported version."
            )

        try:
            rows = conn.execute("SELECT slug FROM domains").fetchall()
            domain_slugs = {row[0] for row in rows}
        except sqlite3.OperationalError as exc:
            errors.append(f"Could not read domains table: {exc}")
    finally:
        conn.close()

    return errors, domain_slugs


@dataclass
class RestoreReport:
    domains_restored: int
    conversations_restored: int
    messages_restored: int
    documents_restored: int
    domain_summaries_restored: int
    skills_restored: int
    schema_revision_before: str | None
    schema_revision_after: str
    rollback_dir: Path | None
    target_dir: Path
    hermes_profile_export_path: Path | None = None
    hermes_profile_import_command: str | None = None


def _target_has_existing_data(target_dir: Path) -> bool:
    db_path = target_dir / "database" / "jarvis.sqlite"
    return db_path.exists()


def _copy_tree_if_present(source_root: Path, name: str, dest_root: Path) -> int:
    source = source_root / name
    if not source.exists():
        return 0
    dest = dest_root / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, symlinks=False)
    return sum(1 for p in dest.rglob("*") if p.is_file())


def restore_archive(
    archive_path: Path,
    target_settings: Settings,
    confirm_overwrite: bool = False,
) -> RestoreReport:
    validation = validate_archive(archive_path)
    if not validation.ok:
        raise ValidationError("; ".join(validation.errors))

    assert validation.extracted_dir is not None
    extracted_dir = validation.extracted_dir

    try:
        target_dir = target_settings.data_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        target_has_data = _target_has_existing_data(target_dir)
        if target_has_data and not confirm_overwrite:
            raise RestoreError(
                f"Target data directory {target_dir} already contains a database. "
                "Pass confirm_overwrite=True (CLI: --confirm) to replace it."
            )

        schema_revision_before = read_db_revision(target_settings.database_path)

        rollback_dir: Path | None = None
        if target_has_data:
            rollback_dir = _create_rollback_copy(target_dir)

        try:
            target_settings.ensure_directories()

            # Replace the database with the validated snapshot.
            target_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extracted_dir / DATABASE_ARCHIVE_PATH, target_settings.database_path)

            # Replace optional payload directories only if the archive declared them.
            documents_restored = _copy_tree_if_present(extracted_dir, "documents", target_dir)
            summaries_restored = _copy_tree_if_present(
                extracted_dir, "domain-summaries", target_dir
            )
            skills_restored = _copy_tree_if_present(extracted_dir, "skills", target_dir)
            _copy_tree_if_present(extracted_dir, "configuration", target_dir)

            # Bring the restored database up to this codebase's current head
            # (a no-op if it's already there; supported for an older, known revision).
            upgrade_database_to_head(target_settings.database_url)
            _assert_database_healthy(target_settings.database_path)
            _expire_stale_action_proposals(target_settings.database_path)
            _disconnect_all_integrations(target_settings.database_path)
            _disable_all_integration_schedules(target_settings.database_path)
            _disable_all_routine_schedules(target_settings.database_path)
            _interrupt_active_focus_sessions(target_settings.database_path)

            restore_counts = _count_restored_rows(target_settings.database_path)
            schema_revision_after = read_db_revision(target_settings.database_path)
            assert schema_revision_after is not None

        except Exception as exc:
            if rollback_dir is not None:
                _restore_from_rollback(rollback_dir, target_dir)
            raise RestoreError(f"Restore failed and was rolled back: {exc}") from exc

        # Hermes profile restoration is deliberately NOT automatic: an
        # existing Hermes profile on this machine is never overwritten as a
        # side effect of a Jarvis restore. If the archive included one, copy
        # it out to a location next to (not inside) JARVIS_DATA_DIR and
        # report the exact confirmation-based command to import it manually.
        hermes_export_path: Path | None = None
        hermes_import_command: str | None = None
        hermes_export = validation.manifest.get("hermes_profile_export") or {}
        if hermes_export.get("included"):
            source = extracted_dir / hermes_export["archive_path"]
            profile_name = hermes_export.get("profile_name", "jarvis")
            dest = target_dir.parent / f"{profile_name}-hermes-profile-import.tar.gz"
            shutil.copy2(source, dest)
            hermes_export_path = dest
            hermes_import_command = f"hermes profile import {dest} --name {profile_name}"

        return RestoreReport(
            domains_restored=restore_counts["domains"],
            conversations_restored=restore_counts["conversations"],
            messages_restored=restore_counts["messages"],
            documents_restored=documents_restored,
            domain_summaries_restored=summaries_restored,
            skills_restored=skills_restored,
            schema_revision_before=schema_revision_before,
            schema_revision_after=schema_revision_after,
            rollback_dir=rollback_dir,
            target_dir=target_dir,
            hermes_profile_export_path=hermes_export_path,
            hermes_profile_import_command=hermes_import_command,
        )
    finally:
        shutil.rmtree(extracted_dir, ignore_errors=True)


def _create_rollback_copy(target_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rollback_dir = target_dir.parent / f"{target_dir.name}.rollback-{timestamp}"
    rollback_dir.mkdir(parents=True, exist_ok=False)

    for name in ("database", "documents", "domain-summaries", "skills", "configuration"):
        source = target_dir / name
        if source.exists():
            shutil.copytree(source, rollback_dir / name, symlinks=False)

    # Verify the rollback copy is usable before trusting it as a safety net.
    rollback_db = rollback_dir / "database" / "jarvis.sqlite"
    if rollback_db.exists():
        conn = sqlite3.connect(str(rollback_db))
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            if not rows or rows[0][0] != "ok":
                raise RestoreError("Rollback copy failed its own integrity check; aborting restore.")
        finally:
            conn.close()

    return rollback_dir


def _restore_from_rollback(rollback_dir: Path, target_dir: Path) -> None:
    for name in ("database", "documents", "domain-summaries", "skills", "configuration"):
        source = rollback_dir / name
        dest = target_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        if source.exists():
            shutil.copytree(source, dest, symlinks=False)


def _assert_database_healthy(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        if not rows or rows[0][0] != "ok":
            raise RestoreError(f"Restored database failed post-migration integrity check: {rows}")
        domain_slugs = {row[0] for row in conn.execute("SELECT slug FROM domains").fetchall()}
        missing = EXPECTED_DOMAIN_SLUGS - domain_slugs
        if missing:
            raise RestoreError(f"Restored database is missing required domains: {sorted(missing)}")
    finally:
        conn.close()


def _count_restored_rows(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        domains = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
        conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return {"domains": domains, "conversations": conversations, "messages": messages}
    finally:
        conn.close()


def _expire_stale_action_proposals(db_path: Path) -> int:
    """Phase 8 safety measure: a pending/approved action proposal must never
    become executable merely because an archive was restored — restoring
    resumes stored data, not an in-flight approval from a different session.
    No-ops cleanly against a pre-Phase-8 database that has no such table."""
    conn = sqlite3.connect(str(db_path))
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='action_proposals'"
        ).fetchone()
        if table_exists is None:
            return 0
        expired_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM action_proposals WHERE status IN ('proposed', 'approved', 'executing')"
            ).fetchall()
        ]
        cursor = conn.execute(
            "UPDATE action_proposals SET status = 'expired' "
            "WHERE status IN ('proposed', 'approved', 'executing')"
        )
        conn.commit()
        if cursor.rowcount > 0:
            now = datetime.now(timezone.utc).isoformat()
            conn.executemany(
                "INSERT INTO action_audit_events (id, action_proposal_id, event_type, detail, created_at) "
                "VALUES (lower(hex(randomblob(16))), ?, 'expired', 'Expired on restore — no pending or "
                "in-flight action survives an import.', ?)",
                [(pid, now) for pid in expired_ids],
            )
            conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _disconnect_all_integrations(db_path: Path) -> int:
    """Phase 9 safety measure: restoring cached integration data must never
    imply the integration is still connected — the real OAuth tokens live
    only in this machine's Keychain (never in the exported database), so a
    restored installation always requires reauthorization. No-ops cleanly
    against a pre-Phase-9 database that has no such table."""
    conn = sqlite3.connect(str(db_path))
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='integration_connections'"
        ).fetchone()
        if table_exists is None:
            return 0
        cursor = conn.execute(
            "UPDATE integration_connections SET status = 'disconnected', scopes_json = '[]', "
            "connected_at = NULL, last_error = 'Reauthorization required after restore.' "
            "WHERE status != 'disconnected'"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _disable_all_integration_schedules(db_path: Path) -> int:
    """Phase 10 safety measure: a restored installation must never resume
    automatic sync against a provider that's simultaneously been forced
    disconnected by `_disconnect_all_integrations` above — Bernardo must
    explicitly reconnect and re-enable automatic sync after a restore.
    No-ops cleanly against a pre-Phase-10 database with no such table."""
    conn = sqlite3.connect(str(db_path))
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='integration_sync_schedules'"
        ).fetchone()
        if table_exists is None:
            return 0
        cursor = conn.execute(
            "UPDATE integration_sync_schedules SET enabled = 0, next_due_at = NULL WHERE enabled != 0"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _disable_all_routine_schedules(db_path: Path) -> int:
    """Phase 10B safety measure: a restored installation must preserve
    historical routine outputs (they're just local text with source
    references, no credential involved) but never resume proactive
    routines automatically — Bernardo must explicitly re-enable each one.
    No-ops cleanly against a pre-Phase-10B database with no such table."""
    conn = sqlite3.connect(str(db_path))
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routine_schedules'"
        ).fetchone()
        if table_exists is None:
            return 0
        cursor = conn.execute(
            "UPDATE routine_schedules SET enabled = 0, next_due_at = NULL WHERE enabled != 0"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def _interrupt_active_focus_sessions(db_path: Path) -> int:
    """Mission Control safety measure: an active or paused focus session
    must never silently keep running on a *different* installation than
    the one it was started on — an ordinary restart on the SAME
    installation preserves it (nothing here runs then), but restoring
    into any installation (the same one or a new one) always forces it
    into a safe terminal state first, exactly like Phase 8's in-flight
    action proposals above. `abandoned_reason` records this was a
    restore-forced interruption, distinct from a genuine user abandon.
    Folds any in-progress pause into `accumulated_paused_seconds` row by
    row in Python (rather than fragile in-SQL date-string arithmetic) so
    the final historical `elapsed_seconds` reading for an interrupted-
    while-paused session stays accurate. No-ops cleanly against a
    pre-Mission-Control database with no such table."""
    conn = sqlite3.connect(str(db_path))
    try:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='focus_sessions'"
        ).fetchone()
        if table_exists is None:
            return 0
        now = datetime.now(timezone.utc)
        rows = conn.execute(
            "SELECT id, status, paused_at, accumulated_paused_seconds FROM focus_sessions "
            "WHERE status IN ('active', 'paused')"
        ).fetchall()
        for row_id, status, paused_at_raw, accumulated in rows:
            new_accumulated = accumulated
            if status == "paused" and paused_at_raw:
                paused_at = datetime.fromisoformat(paused_at_raw)
                if paused_at.tzinfo is None:
                    paused_at = paused_at.replace(tzinfo=timezone.utc)
                new_accumulated += max(0, int((now - paused_at).total_seconds()))
            conn.execute(
                "UPDATE focus_sessions SET status = 'abandoned', completed_at = ?, "
                "abandoned_reason = 'restored_into_installation', paused_at = NULL, "
                "accumulated_paused_seconds = ? WHERE id = ?",
                (now.isoformat(), new_accumulated, row_id),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()
