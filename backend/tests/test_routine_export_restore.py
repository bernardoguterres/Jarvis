"""Phase 10B: routine configuration and historical outputs survive
export/restore, but every schedule is forced disabled afterward — mirrors
the existing Phase 9/10A restore-safety pattern exactly."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models_routines import RoutineRun, RoutineSchedule
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_routine_config_and_history_survive_export_restore_but_disabled(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    with build_sessionmaker(engine_a)() as session:
        seed_domains(session)
        schedule = session.get(RoutineSchedule, "morning_briefing")
        schedule.enabled = True
        schedule.local_time = "07:30"
        schedule.timezone = "Europe/Lisbon"
        schedule.next_due_at = datetime.now(timezone.utc)
        session.add(
            RoutineRun(
                routine_type="morning_briefing",
                trigger="manual",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                outcome="succeeded",
                output_json='{"sections": [{"title": "Today\\u0027s Calendar events", "lines": []}]}',
                selected_domains_json="[]",
            )
        )
        session.commit()
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    engine_b = build_engine(Settings(jarvis_data_dir=str(install_b)).database_url)
    with build_sessionmaker(engine_b)() as session:
        restored_schedule = session.get(RoutineSchedule, "morning_briefing")
        assert restored_schedule.enabled is False
        assert restored_schedule.next_due_at is None
        # Configuration itself (cadence/timezone) is preserved, just disabled.
        assert restored_schedule.local_time == "07:30"
        assert restored_schedule.timezone == "Europe/Lisbon"

        runs = session.query(RoutineRun).filter(RoutineRun.routine_type == "morning_briefing").all()
        assert len(runs) == 1
        assert runs[0].outcome == "succeeded"
        assert "Calendar" in runs[0].output_json
    engine_b.dispose()
