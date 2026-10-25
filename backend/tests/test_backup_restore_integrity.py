"""Regression tests for backups, migrations and restore coordination.

Before the fix, automatic backups ran only at backend startup (the real
installation's newest backup was weeks older than its data), nothing was
snapshotted before a schema upgrade, overlapping backups and restores were
not coordinated, and the restore report always said 0 domain summaries and
0 skills.
"""

from __future__ import annotations

import io
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import backup_service
from app.config import Settings, get_settings
from app.export_service import create_export
from app.import_service import RestoreError, restore_archive
from app.migration_info import get_head_revision, read_db_revision


def _backup_files(settings: Settings, category: str) -> list[str]:
    folder = settings.backups_dir / category
    return sorted(p.name for p in folder.glob("jarvis-backup-*.sqlite")) if folder.exists() else []


def _age_backups(settings: Settings, category: str, hours: int) -> None:
    """Renames existing backups as if they were taken `hours` ago."""
    for path in (settings.backups_dir / category).glob("jarvis-backup-*.sqlite"):
        old = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y%m%d-%H%M%S")
        new = path.with_name(f"jarvis-backup-{category}-{old}.sqlite")
        path.rename(new)
        sidecar = path.with_name(path.name + ".sha256")
        if sidecar.exists():
            sidecar.rename(new.with_name(new.name + ".sha256"))


def test_scheduler_tick_creates_a_due_backup_while_running(memory_settings: Settings) -> None:
    from app.credential_store import FakeCredentialStore
    from app.database import build_engine, build_sessionmaker
    from app.scheduler_runtime import SchedulerRuntime

    backup_service.run_due_backups(memory_settings)
    assert len(_backup_files(memory_settings, "daily")) == 1
    _age_backups(memory_settings, "daily", hours=25)

    engine = build_engine(memory_settings.database_url)
    runtime = SchedulerRuntime(
        build_sessionmaker(engine),
        FakeCredentialStore(),
        None,
        backup_settings=memory_settings,
        backup_check_interval_seconds=0,
    )
    try:
        runtime._run_tick()
    finally:
        engine.dispose()
    assert len(_backup_files(memory_settings, "daily")) == 2
    info = backup_service.get_latest_backup_info(memory_settings)
    assert info["overdue"] is False
    assert info["last_error"] is None


def test_overdue_is_reported_when_the_newest_daily_backup_is_old(memory_settings: Settings) -> None:
    backup_service.run_due_backups(memory_settings)
    _age_backups(memory_settings, "daily", hours=30)
    assert backup_service.get_latest_backup_info(memory_settings)["overdue"] is True


def test_due_check_skips_while_another_backup_or_restore_holds_the_lock(memory_settings: Settings) -> None:
    with backup_service.backup_lock(memory_settings):
        assert backup_service.run_due_backups(memory_settings) == []
    assert len(backup_service.run_due_backups(memory_settings)) == 3


def test_failed_due_backup_is_recorded_and_shown(memory_settings: Settings, monkeypatch) -> None:
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(backup_service, "_snapshot_sqlite", boom)
    assert backup_service.run_due_backups(memory_settings) == []
    info = backup_service.get_latest_backup_info(memory_settings)
    assert "daily backup failed" in info["last_error"]
    assert info["overdue"] is True


def test_pre_migration_backup_is_taken_only_when_an_upgrade_is_pending(data_dir: Path) -> None:
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    settings.ensure_directories()
    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "0018")

    result = backup_service.backup_before_migration(settings)
    assert result is not None and result.category == "pre_migration"
    assert read_db_revision(result.path) == "0018"

    command.upgrade(cfg, "head")
    assert backup_service.backup_before_migration(settings) is None
    assert read_db_revision(settings.database_path) == get_head_revision()


def test_failed_pre_migration_snapshot_raises_so_migration_stops(data_dir: Path, monkeypatch) -> None:
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    settings.ensure_directories()
    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "0018")

    monkeypatch.setattr(backup_service, "_snapshot_sqlite", lambda s, d: (_ for _ in ()).throw(OSError("nope")))
    with pytest.raises(backup_service.BackupError):
        backup_service.backup_before_migration(settings)


def test_restore_report_counts_database_summaries_skills_memories_and_records(
    client: TestClient, tmp_path: Path
) -> None:
    assert client.put("/api/domains/build/summary", json={"content": "Build summary"}).status_code == 200
    assert (
        client.post(
            "/api/skills",
            json={
                "slug": "count-me",
                "name": "Count me",
                "description": "d",
                "domain_slug": None,
                "workflow_steps": [{"capability_id": "memory.create", "description": "x"}],
            },
        ).status_code
        in (200, 201)
    )
    client.post("/api/memories", json={"scope": "global", "kind": "fact", "title": "m", "content": "c"})
    client.post("/api/domains/life/records", json={"record_type": "life_task", "occurred_at": "2026-10-01T10:00:00Z", "payload": {"title": "t"}})
    archive = create_export(get_settings()).path

    report = restore_archive(archive, Settings(jarvis_data_dir=str(tmp_path / "other")))
    assert report.domain_summaries_restored == 1
    assert report.skills_restored >= 1
    assert report.memories_restored == 1
    assert report.structured_records_restored == 1


def test_restore_refuses_while_a_backup_holds_the_lock(populated_settings: Settings, tmp_path: Path) -> None:
    archive = create_export(populated_settings).path
    target = Settings(jarvis_data_dir=str(tmp_path / "t"))
    target.ensure_directories()
    with backup_service.backup_lock(target):
        with pytest.raises(RestoreError, match="in progress"):
            restore_archive(archive, target)


def test_restore_refuses_when_a_hot_journal_exists(populated_settings: Settings) -> None:
    archive = create_export(populated_settings).path
    journal = populated_settings.database_path.with_name("jarvis.sqlite-journal")
    journal.write_bytes(b"x")
    try:
        with pytest.raises(RestoreError, match="journal"):
            restore_archive(archive, populated_settings, confirm_overwrite=True)
    finally:
        journal.unlink()


def test_failed_restore_rolls_back_to_the_previous_data(populated_settings: Settings, monkeypatch) -> None:
    from app import import_service

    archive = create_export(populated_settings).path
    conn = sqlite3.connect(str(populated_settings.database_path))
    conn.execute("UPDATE conversations SET title='after-export'")
    conn.commit()
    conn.close()

    def broken(db_path):
        raise RuntimeError("simulated post-migration failure")

    monkeypatch.setattr(import_service, "_assert_database_healthy", broken)
    with pytest.raises(RestoreError, match="rolled back"):
        restore_archive(archive, populated_settings, confirm_overwrite=True)

    conn = sqlite3.connect(str(populated_settings.database_path))
    try:
        titles = {r[0] for r in conn.execute("SELECT title FROM conversations")}
        assert titles == {"after-export"}
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_api_restore_waits_for_in_flight_requests_and_blocks_new_ones(client: TestClient) -> None:
    """Holds a request open inside a handler, starts a restore, and checks
    the restore waits for it while new requests get a 503."""
    import asyncio

    gate = client.app.state.maintenance
    archive = create_export(get_settings()).path
    payload = archive.read_bytes()

    async def hold():
        async with gate.exclusive(timeout=5):
            await asyncio.sleep(0.3)

    # While the gate is closed, ordinary API calls are refused with 503.
    results: dict[str, int] = {}

    def during() -> None:
        time.sleep(0.1)
        results["during"] = client.get("/api/domains").status_code
        results["health"] = client.get("/api/health").status_code

    t = threading.Thread(target=during)
    t.start()
    client.portal.call(hold)
    t.join()
    assert results == {"during": 503, "health": 200}

    r = client.post(
        "/api/restore",
        files={"file": ("x.zip", io.BytesIO(payload), "application/zip")},
        data={"confirm": "true"},
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/domains").status_code == 200
