"""Phase 9 round-trip: imported documents/extracted text, normalized
Google Calendar and Google Health caches, and integration metadata all survive
export/restore — but every integration connection is forced back to
disconnected (reauthorization required), regardless of its status before
export, since real OAuth tokens live only in the Keychain, never in the
exported database."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from app import document_service
from app.config import Settings
from app.database import build_engine, build_sessionmaker
from app.export_service import create_export
from app.import_service import restore_archive, validate_archive
from app.migration_info import upgrade_database_to_head
from app.models import Domain
from app.models_integrations import CalendarCalendar, CalendarEventCache, Document, GoogleHealthDailySummary, IntegrationConnection
from app.models_scheduler import IntegrationSyncSchedule
from app.seed import seed_domains


def _make_installation(root: Path) -> Settings:
    settings = Settings(jarvis_data_dir=str(root))
    settings.ensure_directories()
    upgrade_database_to_head(settings.database_url)
    return settings


def test_phase9_data_survives_export_and_restore(tmp_path: Path) -> None:
    install_a = _make_installation(tmp_path / "installation-a")
    engine_a = build_engine(install_a.database_url)
    session_factory_a = build_sessionmaker(engine_a)

    with session_factory_a() as session:
        seed_domains(session)
        body = session.query(Domain).filter_by(slug="body").one()

        doc = document_service.import_document(
            session, install_a, domain_id=body.id, original_filename="knee.txt", data=b"Knee history: mild pain after running."
        )
        document_id = doc.id

        session.add(
            IntegrationConnection(
                provider="google_calendar", status="connected", scopes_json="[]", connected_at=datetime.now(timezone.utc)
            )
        )
        session.add(
            IntegrationConnection(provider="google_health", status="connected", scopes_json="[]", connected_at=datetime.now(timezone.utc))
        )
        calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True, selected=True)
        session.add(calendar)
        session.flush()
        session.add(CalendarEventCache(calendar_id=calendar.id, external_event_id="ev1", title="Dentist", all_day=True))
        session.add(GoogleHealthDailySummary(date=date(2026, 8, 1), steps=8000))

        # Phase 10: an enabled automatic-sync schedule must not survive a
        # restore enabled (the connection it depends on is force-disconnected).
        cal_schedule = session.get(IntegrationSyncSchedule, "google_calendar")
        cal_schedule.enabled = True
        cal_schedule.interval_minutes = 30
        cal_schedule.next_due_at = datetime.now(timezone.utc)
        session.commit()
        calendar_id = calendar.id
    engine_a.dispose()

    export_result = create_export(install_a)
    validation = validate_archive(export_result.path)
    assert validation.ok, validation.errors

    install_b = tmp_path / "installation-b"
    restore_archive(export_result.path, Settings(jarvis_data_dir=str(install_b)))

    settings_b = Settings(jarvis_data_dir=str(install_b))
    engine_b = build_engine(settings_b.database_url)
    with build_sessionmaker(engine_b)() as session:
        # Documents + extracted text survive and remain readable.
        restored_doc = session.get(Document, document_id)
        assert restored_doc is not None
        assert restored_doc.status == "ready"
        assert len(restored_doc.chunks) == 1
        assert "Knee history" in restored_doc.chunks[0].content
        stored_file = settings_b.documents_dir / restored_doc.stored_relative_path
        assert stored_file.exists()  # the original file itself, not just the DB row

        # Normalized caches survive.
        restored_calendar = session.get(CalendarCalendar, calendar_id)
        assert restored_calendar is not None
        assert len(restored_calendar.events) == 1
        assert session.query(GoogleHealthDailySummary).count() == 1

        # But BOTH integrations show disconnected — reauthorization required,
        # regardless of their status at export time.
        gcal_conn = session.get(IntegrationConnection, "google_calendar")
        google_health_conn = session.get(IntegrationConnection, "google_health")
        assert gcal_conn.status == "disconnected"
        assert google_health_conn.status == "disconnected"

        # Phase 10: automatic sync must not resume enabled after a restore —
        # the connection it depends on is force-disconnected in this same step.
        restored_cal_schedule = session.get(IntegrationSyncSchedule, "google_calendar")
        assert restored_cal_schedule.enabled is False
        assert restored_cal_schedule.next_due_at is None

        # Documents remain searchable (FTS is rebuilt post-restore, like memory).
        from app.document_fts_service import rebuild_document_fts, search_document_fts

        rebuild_document_fts(session)
        hits = search_document_fts(session, "knee")
        assert len(hits) == 1

        # The restored installation remains writable: a new document import works.
        body = session.query(Domain).filter_by(slug="body").one()
        new_doc = document_service.import_document(
            session, settings_b, domain_id=body.id, original_filename="post-restore.txt", data=b"writability check"
        )
        assert new_doc.id
    engine_b.dispose()
