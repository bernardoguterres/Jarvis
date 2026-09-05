"""Phase 12C: Mission Focus pins survive export/restore, remain writable
afterward, and — since a pin holds no live schedule/connection/proposal
state — need no restore-time safety-forcing the way routine/integration
schedules and action proposals do."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Domain
from app.models_memory import StructuredRecord
from app.models_mission_focus import MissionFocusPin
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_mission_focus_pins_survive_export_restore_and_stay_writable(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=now,
            payload_json=json.dumps({"title": "Renew passport", "due_date": "2020-01-01"}),
        )
        session.add(record)
        session.commit()

        from app import mission_focus_service as mfs

        pin = mfs.create_pin(session, source_type="life_task", source_id=record.id, next_action="Book slot", clock=lambda: now)
        pin_id = pin.id
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        pins = session.query(MissionFocusPin).filter_by(status="active").all()
        assert len(pins) == 1
        assert pins[0].id == pin_id
        assert pins[0].next_action == "Book slot"
        assert pins[0].domain_slug == "life"

        # A post-restore write succeeds — genuinely usable, not read-only.
        from app import mission_focus_service as mfs

        life = session.query(Domain).filter_by(slug="life").one()
        record2 = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=now,
            payload_json=json.dumps({"title": "Second task", "due_date": "2026-09-01"}),
        )
        session.add(record2)
        session.commit()
        new_pin = mfs.create_pin(session, source_type="life_task", source_id=record2.id, next_action="Do it", clock=lambda: now)
        assert new_pin.rank == 2
        assert session.query(MissionFocusPin).filter_by(status="active").count() == 2
    engine_b.dispose()


def test_restore_never_reactivates_or_deletes_a_pin(tmp_path: Path) -> None:
    """A restored Mission Focus pin's status must be preserved exactly as
    exported (no forcing to inactive, no deletion) — unlike a live
    schedule, a pin carries no external side effect that restoring could
    reactivate."""
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=now,
            payload_json=json.dumps({"title": "Renew passport", "due_date": "2020-01-01"}),
        )
        session.add(record)
        session.commit()

        from app import mission_focus_service as mfs

        pin = mfs.create_pin(session, source_type="life_task", source_id=record.id, next_action="Book slot", clock=lambda: now)
        mfs.unpin(session, pin.id, clock=lambda: now)
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        rows = session.query(MissionFocusPin).all()
        assert len(rows) == 1
        assert rows[0].status == "unpinned"  # preserved exactly, never reactivated
    engine_b.dispose()


def test_no_secrets_in_mission_focus_export(tmp_path: Path) -> None:
    import zipfile

    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        record = StructuredRecord(
            domain_id=life.id, record_type="life_task", occurred_at=now,
            payload_json=json.dumps({"title": "Renew passport", "due_date": "2020-01-01"}),
        )
        session.add(record)
        session.commit()

        from app import mission_focus_service as mfs

        mfs.create_pin(session, source_type="life_task", source_id=record.id, next_action="Book slot", clock=lambda: now)
    engine_a.dispose()

    export_result = create_export(install_a)
    with zipfile.ZipFile(export_result.path) as zf:
        names = zf.namelist()
        assert not any(n.endswith(".env") or "auth.json" in n for n in names)
