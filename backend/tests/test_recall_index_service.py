"""Phase 12D: the write side of the unified Recall index —
sync_recall/remove_recall/rebuild_recall_index, one source type at a
time. Every test uses fictional fixtures — no real Calendar/Health/
Keychain/Hermes contact, matching every other Phase 12 test suite."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import recall_index_service as ris
from app.models import Conversation, Domain, Message
from app.models_actions import ActionProposal
from app.models_integrations import CalendarCalendar, CalendarEventCache, Document
from app.models_memory import DomainSummary, DomainSummaryVersion, StructuredRecord
from app.models_mission_control import FocusSession
from app.models_routines import RoutineRun

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)


def _domain_id(db_session: Session, slug: str) -> str:
    return db_session.query(Domain).filter_by(slug=slug).one().id


def _recall_rows(db_session: Session, source_type: str, source_id: str) -> list:
    return db_session.execute(
        text("SELECT title, content, domain_slug, occurred_at FROM recall_fts WHERE source_type = :t AND source_id = :i"),
        {"t": source_type, "i": source_id},
    ).all()


def _recall_count(db_session: Session) -> int:
    return db_session.execute(text("SELECT COUNT(*) FROM recall_fts")).scalar_one()


# --- conversation / message ---------------------------------------------------


def test_conversation_indexed_with_its_title(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    conv = Conversation(domain_id=life_id, title="Renew passport plan")
    db_session.add(conv)
    db_session.commit()

    assert ris.sync_recall(db_session, "conversation", conv.id) is True
    db_session.commit()
    rows = _recall_rows(db_session, "conversation", conv.id)
    assert len(rows) == 1
    assert rows[0][0] == "Renew passport plan"
    assert rows[0][2] == "life"


def test_general_conversation_has_no_domain_slug(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="General chat")
    db_session.add(conv)
    db_session.commit()
    ris.sync_recall(db_session, "conversation", conv.id)
    db_session.commit()
    rows = _recall_rows(db_session, "conversation", conv.id)
    assert rows[0][2] is None


def test_archived_conversation_is_removed_not_indexed(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="Old chat")
    db_session.add(conv)
    db_session.commit()
    ris.sync_recall(db_session, "conversation", conv.id)
    db_session.commit()
    assert len(_recall_rows(db_session, "conversation", conv.id)) == 1

    conv.archived_at = NOW
    db_session.commit()
    assert ris.sync_recall(db_session, "conversation", conv.id) is False
    db_session.commit()
    assert len(_recall_rows(db_session, "conversation", conv.id)) == 0


def test_message_indexed_with_conversation_domain(db_session: Session) -> None:
    build_id = _domain_id(db_session, "build")
    conv = Conversation(domain_id=build_id, title="Tokenizer work")
    db_session.add(conv)
    db_session.flush()
    message = Message(conversation_id=conv.id, role="user", content="Fix the BPE merge bug")
    db_session.add(message)
    db_session.commit()

    ris.sync_recall(db_session, "message", message.id)
    db_session.commit()
    rows = _recall_rows(db_session, "message", message.id)
    assert rows[0][1] == "Fix the BPE merge bug"
    assert rows[0][2] == "build"


def test_message_removed_when_its_conversation_is_archived(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="X")
    db_session.add(conv)
    db_session.flush()
    message = Message(conversation_id=conv.id, role="assistant", content="reply text")
    db_session.add(message)
    db_session.commit()
    ris.sync_recall(db_session, "message", message.id)
    db_session.commit()

    conv.archived_at = NOW
    db_session.commit()
    assert ris.sync_recall(db_session, "message", message.id) is False
    db_session.commit()
    assert len(_recall_rows(db_session, "message", message.id)) == 0


def test_message_removed_when_deleted(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="X")
    db_session.add(conv)
    db_session.flush()
    message = Message(conversation_id=conv.id, role="user", content="gone soon")
    db_session.add(message)
    db_session.commit()
    ris.sync_recall(db_session, "message", message.id)
    db_session.commit()
    message_id = message.id

    db_session.delete(message)
    db_session.commit()
    ris.remove_recall(db_session, "message", message_id)
    db_session.commit()
    assert len(_recall_rows(db_session, "message", message_id)) == 0


# --- structured records --------------------------------------------------------


def test_structured_record_indexed_with_flattened_payload(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    record = StructuredRecord(
        domain_id=life_id, record_type="life_task", occurred_at=NOW,
        payload_json=json.dumps({"title": "Renew passport", "due_date": "2026-09-01"}),
    )
    db_session.add(record)
    db_session.commit()
    ris.sync_recall(db_session, "structured_record", record.id)
    db_session.commit()
    rows = _recall_rows(db_session, "structured_record", record.id)
    assert rows[0][0] == "Renew passport"
    assert "2026-09-01" in rows[0][1]


def test_archived_structured_record_is_removed(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    record = StructuredRecord(
        domain_id=life_id, record_type="life_task", occurred_at=NOW, payload_json=json.dumps({"title": "Task"})
    )
    db_session.add(record)
    db_session.commit()
    ris.sync_recall(db_session, "structured_record", record.id)
    db_session.commit()

    record.archived_at = NOW
    db_session.commit()
    assert ris.sync_recall(db_session, "structured_record", record.id) is False
    db_session.commit()
    assert len(_recall_rows(db_session, "structured_record", record.id)) == 0


def test_structured_record_without_title_falls_back_to_record_type(db_session: Session) -> None:
    build_id = _domain_id(db_session, "build")
    record = StructuredRecord(
        domain_id=build_id, record_type="build_checkpoint", occurred_at=NOW,
        payload_json=json.dumps({"project": "Alpha", "summary": "Shipped fix"}),
    )
    db_session.add(record)
    db_session.commit()
    ris.sync_recall(db_session, "structured_record", record.id)
    db_session.commit()
    rows = _recall_rows(db_session, "structured_record", record.id)
    assert rows[0][0] == "Build Checkpoint"


# --- domain summaries -----------------------------------------------------------


def test_domain_summary_indexed_when_set(db_session: Session) -> None:
    path_id = _domain_id(db_session, "path")
    summary = DomainSummary(domain_id=path_id)
    db_session.add(summary)
    db_session.flush()
    version = DomainSummaryVersion(domain_summary_id=summary.id, version_number=1, content="Focused on UCL applications.")
    db_session.add(version)
    db_session.flush()
    summary.current_version_id = version.id
    db_session.commit()

    ris.sync_recall(db_session, "domain_summary", path_id)
    db_session.commit()
    rows = _recall_rows(db_session, "domain_summary", path_id)
    assert "UCL applications" in rows[0][1]
    assert rows[0][2] == "path"


def test_domain_with_no_summary_is_not_indexable(db_session: Session) -> None:
    path_id = _domain_id(db_session, "path")
    assert ris.sync_recall(db_session, "domain_summary", path_id) is False


def test_cleared_domain_summary_is_removed(db_session: Session) -> None:
    path_id = _domain_id(db_session, "path")
    summary = DomainSummary(domain_id=path_id)
    db_session.add(summary)
    db_session.flush()
    version = DomainSummaryVersion(domain_summary_id=summary.id, version_number=1, content="Some content")
    db_session.add(version)
    db_session.flush()
    summary.current_version_id = version.id
    db_session.commit()
    ris.sync_recall(db_session, "domain_summary", path_id)
    db_session.commit()

    summary.current_version_id = None
    db_session.commit()
    assert ris.sync_recall(db_session, "domain_summary", path_id) is False
    db_session.commit()
    assert len(_recall_rows(db_session, "domain_summary", path_id)) == 0


# --- documents --------------------------------------------------------------


def test_ready_document_indexed_by_filename(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    doc = Document(
        domain_id=life_id, original_filename="lease-agreement.pdf", stored_relative_path="x/y.pdf",
        mime_type="application/pdf", sha256="a" * 64, size_bytes=100, status="ready",
    )
    db_session.add(doc)
    db_session.commit()
    ris.sync_recall(db_session, "document", doc.id)
    db_session.commit()
    rows = _recall_rows(db_session, "document", doc.id)
    assert rows[0][0] == "lease-agreement.pdf"


def test_processing_document_not_indexed(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    doc = Document(
        domain_id=life_id, original_filename="x.pdf", stored_relative_path="x/y.pdf",
        mime_type="application/pdf", sha256="b" * 64, size_bytes=100, status="processing",
    )
    db_session.add(doc)
    db_session.commit()
    assert ris.sync_recall(db_session, "document", doc.id) is False


def test_deleted_document_removed(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    doc = Document(
        domain_id=life_id, original_filename="x.pdf", stored_relative_path="x/y.pdf",
        mime_type="application/pdf", sha256="c" * 64, size_bytes=100, status="ready",
    )
    db_session.add(doc)
    db_session.commit()
    ris.sync_recall(db_session, "document", doc.id)
    db_session.commit()
    doc_id = doc.id
    db_session.delete(doc)
    db_session.commit()
    ris.remove_recall(db_session, "document", doc_id)
    db_session.commit()
    assert len(_recall_rows(db_session, "document", doc_id)) == 0


# --- calendar events ----------------------------------------------------------


def test_calendar_event_indexed_as_life_domain(db_session: Session) -> None:
    calendar = CalendarCalendar(external_calendar_id="primary", summary="Bernardo", access_role="owner", is_owned=True)
    db_session.add(calendar)
    db_session.flush()
    event = CalendarEventCache(
        calendar_id=calendar.id, external_event_id="ev1", title="Dentist", location="Clinic",
        start_datetime=datetime(2026, 9, 2, 11, 0, tzinfo=timezone.utc),
    )
    db_session.add(event)
    db_session.commit()
    ris.sync_recall(db_session, "calendar_event", event.id)
    db_session.commit()
    rows = _recall_rows(db_session, "calendar_event", event.id)
    assert rows[0][0] == "Dentist"
    assert rows[0][2] == "life"
    assert "Clinic" in rows[0][1]


# --- action proposals -----------------------------------------------------------


def test_action_proposal_indexed_with_reason_and_effect(db_session: Session) -> None:
    proposal = ActionProposal(
        capability_id="memory.create", domain_id=None, permission_level="confirm", arguments_json="{}",
        reason="User asked to remember this", expected_effect="Create a memory", payload_digest="a" * 64,
        status="proposed",
    )
    db_session.add(proposal)
    db_session.commit()
    ris.sync_recall(db_session, "action_proposal", proposal.id)
    db_session.commit()
    rows = _recall_rows(db_session, "action_proposal", proposal.id)
    assert "remember this" in rows[0][1]
    assert rows[0][2] is None


def test_action_proposal_never_indexes_arguments_json_or_confirmation_token(db_session: Session) -> None:
    proposal = ActionProposal(
        capability_id="memory.create", domain_id=None, permission_level="confirm",
        arguments_json=json.dumps({"secret_argument": "SHOULD_NOT_APPEAR"}),
        reason="ordinary reason", expected_effect="ordinary effect", payload_digest="b" * 64,
        status="proposed", confirmation_token="TOKEN_SHOULD_NOT_APPEAR",
    )
    db_session.add(proposal)
    db_session.commit()
    ris.sync_recall(db_session, "action_proposal", proposal.id)
    db_session.commit()
    rows = _recall_rows(db_session, "action_proposal", proposal.id)
    assert "SHOULD_NOT_APPEAR" not in rows[0][1]
    assert "TOKEN_SHOULD_NOT_APPEAR" not in rows[0][1]


# --- routine runs ---------------------------------------------------------------


def test_routine_run_indexed_with_reason_and_output_text(db_session: Session) -> None:
    run = RoutineRun(
        routine_type="morning_briefing", trigger="manual", started_at=NOW, completed_at=NOW, outcome="succeeded",
        reason=None,
        output_json=json.dumps({"sections": [{"title": "Calendar", "lines": [{"text": "Dentist at 11am", "source_ref": None}]}]}),
        selected_domains_json="[]",
    )
    db_session.add(run)
    db_session.commit()
    ris.sync_recall(db_session, "routine_run", run.id)
    db_session.commit()
    rows = _recall_rows(db_session, "routine_run", run.id)
    assert "Dentist at 11am" in rows[0][1]
    assert rows[0][2] is None


def test_routine_run_malformed_output_json_does_not_crash(db_session: Session) -> None:
    run = RoutineRun(
        routine_type="evening_checkin", trigger="scheduled", started_at=NOW, outcome="failed",
        reason="unexpected error", output_json="{not valid json", selected_domains_json="[]",
    )
    db_session.add(run)
    db_session.commit()
    assert ris.sync_recall(db_session, "routine_run", run.id) is True
    db_session.commit()
    rows = _recall_rows(db_session, "routine_run", run.id)
    assert "unexpected error" in rows[0][1]


# --- mission control sessions ----------------------------------------------------


def test_mission_control_session_indexed_with_title_and_notes(db_session: Session) -> None:
    focus = FocusSession(
        title="Renew passport", domain_id=_domain_id(db_session, "life"), source_type="manual",
        status="completed", target_duration_minutes=25, started_at=NOW, completed_at=NOW,
        accumulated_paused_seconds=0, completion_note="Filed the form", what_changed_note="Application submitted",
    )
    db_session.add(focus)
    db_session.commit()
    ris.sync_recall(db_session, "mission_control_session", focus.id)
    db_session.commit()
    rows = _recall_rows(db_session, "mission_control_session", focus.id)
    assert "Filed the form" in rows[0][1]
    assert "Application submitted" in rows[0][1]
    assert rows[0][2] == "life"


# --- idempotency and unknown source types ---------------------------------------


def test_sync_recall_is_idempotent(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="Idempotent test")
    db_session.add(conv)
    db_session.commit()
    ris.sync_recall(db_session, "conversation", conv.id)
    ris.sync_recall(db_session, "conversation", conv.id)
    db_session.commit()
    assert len(_recall_rows(db_session, "conversation", conv.id)) == 1


def test_sync_recall_rejects_unknown_source_type(db_session: Session) -> None:
    import pytest

    with pytest.raises(ValueError):
        ris.sync_recall(db_session, "not_a_real_source_type", "x")


# --- table-not-existing (pre-migration) resilience -------------------------------


def test_sync_recall_no_ops_cleanly_without_recall_fts_table(db_session: Session) -> None:
    conv = Conversation(domain_id=None, title="Pre-migration scenario")
    db_session.add(conv)
    db_session.commit()
    db_session.execute(text("DROP TABLE recall_fts"))
    db_session.commit()

    assert ris.sync_recall(db_session, "conversation", conv.id) is False
    ris.remove_recall(db_session, "conversation", conv.id)  # must not raise


# --- rebuild -----------------------------------------------------------------


def test_rebuild_recall_index_reindexes_everything_and_excludes_archived(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    conv = Conversation(domain_id=life_id, title="Keep me")
    archived_conv = Conversation(domain_id=life_id, title="Drop me", archived_at=NOW)
    db_session.add_all([conv, archived_conv])
    db_session.commit()

    count = ris.rebuild_recall_index(db_session)
    assert count >= 1
    assert len(_recall_rows(db_session, "conversation", conv.id)) == 1
    assert len(_recall_rows(db_session, "conversation", archived_conv.id)) == 0


def test_rebuild_recall_index_produces_no_ghost_rows_for_deleted_sources(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    record = StructuredRecord(
        domain_id=life_id, record_type="life_task", occurred_at=NOW, payload_json=json.dumps({"title": "Temp"})
    )
    db_session.add(record)
    db_session.commit()
    ris.rebuild_recall_index(db_session)
    assert len(_recall_rows(db_session, "structured_record", record.id)) == 1

    record_id = record.id
    db_session.delete(record)
    db_session.commit()

    ris.rebuild_recall_index(db_session)
    assert len(_recall_rows(db_session, "structured_record", record_id)) == 0


def test_rebuild_recall_index_is_idempotent_in_total_row_count(db_session: Session) -> None:
    life_id = _domain_id(db_session, "life")
    conv = Conversation(domain_id=life_id, title="Stable")
    db_session.add(conv)
    db_session.commit()
    ris.rebuild_recall_index(db_session)
    first_count = _recall_count(db_session)
    ris.rebuild_recall_index(db_session)
    second_count = _recall_count(db_session)
    assert first_count == second_count
