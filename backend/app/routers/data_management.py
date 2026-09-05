"""Export, backup, import-validation, and (Stage 1 native packaging) restore
API endpoints.

Restoration is a genuinely destructive, confirmation-gated operation — it
can replace a live database — so `POST /api/restore` requires an explicit
`confirm=true` before it will overwrite a target that already has data,
mirroring the CLI's own `--confirm` flag exactly (`import_service.py`'s
`restore_archive`, the same function `jarvis-cli restore` calls — there is
only ever one restore implementation). It is exposed here specifically so
the installed native app can offer a guarded, in-product "Restore from
Jarvis export" action (Mac-migration support — see docs/ARCHITECTURE.md
and docs/DECISIONS.md) without requiring a terminal.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.backup_service import BackupError, CATEGORIES, create_backup, get_latest_backup_info
from app.config import Settings, get_settings
from app.export_service import ExportError, ExportInProgressError, create_export
from app.import_service import RestoreError, ValidationError, restore_archive, validate_archive
from app.schemas import (
    BackupRead,
    DataDirRead,
    ExportListItem,
    ExportRead,
    ImportValidationRead,
    LatestBackupInfo,
    RestoreRead,
)

router = APIRouter(tags=["data-management"])

_EXPORT_FILENAME_RE = re.compile(r"^jarvis-export-\d{8}-\d{6}\.zip$")


def get_settings_dep() -> Settings:
    return get_settings()


@router.get("/api/data-dir", response_model=DataDirRead)
def data_dir_endpoint(settings: Settings = Depends(get_settings_dep)) -> DataDirRead:
    """The resolved, absolute JARVIS_DATA_DIR path — non-secret (a local
    filesystem path, already shown in Data Management's own UI copy).
    Used to display the real path and to back the native app's "Reveal
    Jarvis Data Folder" menu action."""
    return DataDirRead(path=str(settings.data_dir))


@router.post("/api/export", response_model=ExportRead, status_code=201)
def create_export_endpoint(settings: Settings = Depends(get_settings_dep)) -> ExportRead:
    try:
        result = create_export(settings)
    except ExportInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ExportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return ExportRead(
        filename=result.filename,
        created_at_utc=result.created_at_utc,
        size_bytes=result.size_bytes,
        included_components=result.manifest.get("included_components", []),
    )


@router.get("/api/exports", response_model=list[ExportListItem])
def list_exports(settings: Settings = Depends(get_settings_dep)) -> list[ExportListItem]:
    exports_dir = settings.exports_dir
    if not exports_dir.exists():
        return []

    items: list[ExportListItem] = []
    for entry in sorted(exports_dir.iterdir(), reverse=True):
        if not entry.is_file() or not _EXPORT_FILENAME_RE.match(entry.name):
            continue
        items.append(
            ExportListItem(
                filename=entry.name,
                size_bytes=entry.stat().st_size,
                created_at_utc=None,
            )
        )
    return items


@router.get("/api/exports/{filename}/download")
def download_export(filename: str, settings: Settings = Depends(get_settings_dep)) -> FileResponse:
    # Only a recognised export filename pattern is ever accepted, and the
    # resolved path must land inside exports_dir — no path traversal via the
    # filename parameter.
    if not _EXPORT_FILENAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="Export not found")

    exports_dir = settings.exports_dir.resolve()
    candidate = (exports_dir / filename).resolve()
    if candidate.parent != exports_dir or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Export not found")

    return FileResponse(candidate, filename=filename, media_type="application/zip")


@router.post("/api/backups", response_model=BackupRead, status_code=201)
def create_backup_endpoint(
    category: str = Query(default="daily"),
    settings: Settings = Depends(get_settings_dep),
) -> BackupRead:
    if category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"category must be one of {CATEGORIES}")

    try:
        result = create_backup(settings, category=category)
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return BackupRead(
        category=result.category,
        filename=result.filename,
        created_at_utc=result.created_at_utc,
        size_bytes=result.size_bytes,
        sha256=result.sha256,
    )


@router.get("/api/backups/latest", response_model=LatestBackupInfo)
def latest_backup(settings: Settings = Depends(get_settings_dep)) -> LatestBackupInfo:
    info = get_latest_backup_info(settings)
    return LatestBackupInfo(**info)


@router.post("/api/imports/validate", response_model=ImportValidationRead)
async def validate_import(file: UploadFile) -> ImportValidationRead:
    with tempfile.TemporaryDirectory(prefix="jarvis-upload-") as tmp_dir:
        upload_path = Path(tmp_dir) / "upload.zip"
        with upload_path.open("wb") as dest:
            shutil.copyfileobj(file.file, dest)

        result = validate_archive(upload_path)
        if result.extracted_dir:
            shutil.rmtree(result.extracted_dir, ignore_errors=True)

    return ImportValidationRead(ok=result.ok, errors=result.errors, manifest=result.manifest)


@router.post("/api/restore", response_model=RestoreRead)
async def restore_import(
    request: Request,
    file: UploadFile,
    confirm: bool = Form(False),
    settings: Settings = Depends(get_settings_dep),
) -> RestoreRead:
    """Restore a validated export archive onto this machine's own real
    JARVIS_DATA_DIR — the guarded action behind the native app's "Restore
    from Jarvis export" UI. `confirm` must be explicitly true to overwrite
    an existing non-empty target, exactly mirroring `jarvis-cli restore
    --confirm`; every other safety behavior (schema/checksum/manifest
    validation, forced-disconnected integrations, forced-disabled
    schedules/routines, rollback-on-failure) lives in `restore_archive`
    itself and is not duplicated here.
    """
    with tempfile.TemporaryDirectory(prefix="jarvis-restore-upload-") as tmp_dir:
        upload_path = Path(tmp_dir) / "upload.zip"
        with upload_path.open("wb") as dest:
            shutil.copyfileobj(file.file, dest)

        # This request's own DB dependency (if any) already released its
        # session by the time this handler body runs; disposing the shared
        # engine's connection pool here — before the database file on disk
        # is replaced — is what lets every *later* checkout (this process
        # never rebuilds the Engine/sessionmaker objects themselves, only
        # clears their pooled connections) transparently open the restored
        # file instead of a stale handle to the file that used to be there.
        request.app.state.engine.dispose()

        try:
            report = restore_archive(upload_path, settings, confirm_overwrite=confirm)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RestoreError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    return RestoreRead(
        domains_restored=report.domains_restored,
        conversations_restored=report.conversations_restored,
        messages_restored=report.messages_restored,
        documents_restored=report.documents_restored,
        domain_summaries_restored=report.domain_summaries_restored,
        skills_restored=report.skills_restored,
        schema_revision_before=report.schema_revision_before,
        schema_revision_after=report.schema_revision_after,
        rollback_dir=str(report.rollback_dir) if report.rollback_dir else None,
        target_dir=str(report.target_dir),
        hermes_profile_export_path=(
            str(report.hermes_profile_export_path) if report.hermes_profile_export_path else None
        ),
        hermes_profile_import_command=report.hermes_profile_import_command,
    )
