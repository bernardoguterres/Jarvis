"""Phase 12B: briefing continuity (snapshots, the per-identity ledger,
acknowledgements, and snoozes) survives export/restore, remains writable,
and — since none of it is a live schedule/connection/proposal — needs no
restore-time safety-forcing the way routine/integration schedules and
action proposals do (see docs/DECISIONS.md D87 for why)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Domain
from app.models_briefing import BriefingAcknowledgement, BriefingItemState, BriefingSnapshot, BriefingSnooze
from app.models_memory import StructuredRecord
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_briefing_continuity_survives_export_restore_and_stays_writable(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    now = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        life = session.query(Domain).filter_by(slug="life").one()
        session.add(
            StructuredRecord(
                domain_id=life.id, record_type="life_task", occurred_at=now,
                payload_json=json.dumps({"title": "Renew passport", "due_date": "2020-01-01"}),
            )
        )
        session.commit()

        from app import briefing_service

        briefing = briefing_service.assemble_home_briefing(
            session, include_body=False, include_mind=False, include_people=False, now=now
        )
        stable_key = briefing.items[0].id
        briefing_service.acknowledge_item(session, stable_key, now)
        session.commit()

    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        ledger_rows = session.query(BriefingItemState).all()
        assert len(ledger_rows) == 1
        assert ledger_rows[0].status == "active"
        assert ledger_rows[0].last_title == "Renew passport"

        acks = session.query(BriefingAcknowledgement).filter_by(status="active").all()
        assert len(acks) == 1

        snapshots = session.query(BriefingSnapshot).filter_by(consumer="home").all()
        assert len(snapshots) == 1

        # A post-restore write succeeds — the restored installation is
        # genuinely usable, not a read-only artifact.
        from app import briefing_service

        briefing_service.snooze_item(session, ledger_rows[0].stable_key, "1h", now + timedelta(hours=2))
        session.commit()
        assert session.query(BriefingSnooze).count() == 1
    engine_b.dispose()


def test_restore_never_reactivates_anything_briefing_related(tmp_path: Path) -> None:
    """No routine/schedule/integration/proposal exists anywhere in this
    dataset, so restoring it must not create or enable one — a negative
    check that the briefing-continuity restore path stays purely additive
    (its own tables only) and never reaches into unrelated subsystems."""
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        session.commit()
    engine_a.dispose()

    export_result = create_export(install_a)
    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        from app.models_actions import ActionProposal
        from app.models_routines import RoutineSchedule
        from app.models_scheduler import IntegrationSyncSchedule

        assert session.query(ActionProposal).count() == 0
        assert all(s.enabled is False for s in session.query(RoutineSchedule).all())
        assert all(s.enabled is False for s in session.query(IntegrationSyncSchedule).all())
    engine_b.dispose()
