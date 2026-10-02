"""Write side of the Recall index: one small, idempotent adapter per
source type, all writing to `recall_fts` (migration 0016). The index is
derived data and can always be rebuilt from the real tables.

`sync_recall` re-renders the real row every time and deletes the index
row when the source is gone, archived or not ready, so one call serves
create, update and archive paths. Adapters only read display-safe
fields, never tokens, credentials, raw provider payloads or routine
output outside LIFE/PATH/BUILD sections. A source with no single owning
domain is stored with `domain_slug=None` (global).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Conversation, Domain, Message
from app.models_actions import ActionProposal
from app.models_decisions import (
    Decision,
    DecisionFactor,
    DecisionFinalVersion,
    DecisionOutcomeReview,
)
from app.models_integrations import CalendarEventCache, Document
from app.models_memory import StructuredRecord
from app.models_mission_control import FocusSession
from app.models_routines import RoutineRun

# The fixed set of source types this module knows how to index. Kept in
# sync with `app/schemas_recall.py`'s `RecallSourceType` Literal. A
# mismatch there is a real defect, not a config typo, since an unlisted
# type could otherwise silently never get indexed or never get removed.
RECALL_SOURCE_TYPES = (
    "conversation",
    "message",
    "structured_record",
    "domain_summary",
    "document",
    "calendar_event",
    "action_proposal",
    "routine_run",
    "mission_control_session",
    "decision",
)


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip even through a `DateTime(timezone=
    True)` column, so normalize before formatting."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        aware = _as_aware(dt)
        return aware.isoformat() if aware else None
    return dt.isoformat()


def _domain_slug(session: Session, domain_id: str | None) -> str | None:
    if domain_id is None:
        return None
    domain = session.get(Domain, domain_id)
    return domain.slug if domain else None


def _recall_fts_table_exists(session: Session) -> bool:
    """A handful of tests (and, in principle, any service-layer code
    invoked mid-migration) deliberately run against a schema revision
    older than 0016, where `recall_fts` does not exist yet. Checked via
    `sqlite_master` (never itself capable of raising "no such table")
    rather than a try/except around the real DML, since a failed DBAPI
    statement would otherwise poison the caller's whole transaction and
    silently roll back unrelated work already pending in the same
    session (e.g. a not-yet-committed `ActionProposal`)."""
    return (
        session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='recall_fts'")).first()
        is not None
    )


def _delete_recall_rows(session: Session, source_type: str, source_id: str) -> None:
    session.execute(
        text("DELETE FROM recall_fts WHERE source_type = :t AND source_id = :i"),
        {"t": source_type, "i": source_id},
    )


def _insert_recall_row(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    domain_slug: str | None,
    occurred_at: str | None,
    title: str,
    content: str,
) -> None:
    session.execute(
        text(
            "INSERT INTO recall_fts (source_type, source_id, domain_slug, occurred_at, title, content) "
            "VALUES (:source_type, :source_id, :domain_slug, :occurred_at, :title, :content)"
        ),
        {
            "source_type": source_type,
            "source_id": source_id,
            "domain_slug": domain_slug,
            "occurred_at": occurred_at,
            "title": title,
            "content": content,
        },
    )


class _NotIndexable(Exception):
    """Raised by an adapter to mean 'this row exists but should not (or no
    longer) appear in recall'. Caught by `sync_recall`, which then only
    ever deletes, never inserts a hollow row."""


def _render_conversation(session: Session, conversation_id: str) -> dict:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.archived_at is not None:
        raise _NotIndexable
    title = conversation.title or "(untitled conversation)"
    return {
        "domain_slug": _domain_slug(session, conversation.domain_id),
        "occurred_at": _iso(conversation.updated_at),
        "title": title,
        "content": title,
    }


def _render_message(session: Session, message_id: str) -> dict:
    message = session.get(Message, message_id)
    if message is None:
        raise _NotIndexable
    conversation = message.conversation
    if conversation is None or conversation.archived_at is not None:
        raise _NotIndexable
    title = conversation.title or "(untitled conversation)"
    return {
        "domain_slug": _domain_slug(session, conversation.domain_id),
        "occurred_at": _iso(message.created_at),
        "title": title,
        "content": message.content,
    }


def _render_structured_record(session: Session, record_id: str) -> dict:
    record = session.get(StructuredRecord, record_id)
    if record is None or record.archived_at is not None:
        raise _NotIndexable
    try:
        payload = json.loads(record.payload_json)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    title = payload.get("title") or record.record_type.replace("_", " ").title()
    # A flat, deterministic rendering of every string-valued payload field
    # without the raw JSON braces/keys as searchable noise, and never a
    # field this record type doesn't actually have.
    content_parts = [str(v) for v in payload.values() if isinstance(v, (str, int, float)) and str(v).strip()]
    return {
        "domain_slug": _domain_slug(session, record.domain_id),
        "occurred_at": _iso(record.occurred_at),
        "title": title,
        "content": " ".join(content_parts) or title,
    }


def _render_domain_summary(session: Session, domain_id: str) -> dict:
    summary = session.execute(
        text("SELECT current_version_id, updated_at FROM domain_summaries WHERE domain_id = :d"), {"d": domain_id}
    ).first()
    if summary is None or summary[0] is None:
        raise _NotIndexable
    version = session.execute(
        text("SELECT content, created_at FROM domain_summary_versions WHERE id = :v"), {"v": summary[0]}
    ).first()
    if version is None or not (version[0] or "").strip():
        raise _NotIndexable
    domain = session.get(Domain, domain_id)
    title = f"{domain.name} summary" if domain else "Domain summary"
    return {
        "domain_slug": domain.slug if domain else None,
        "occurred_at": _iso(version[1]) if isinstance(version[1], datetime) else version[1],
        "title": title,
        "content": version[0],
    }


def _render_document(session: Session, document_id: str) -> dict:
    document = session.get(Document, document_id)
    if document is None or document.status != "ready":
        raise _NotIndexable
    return {
        "domain_slug": _domain_slug(session, document.domain_id),
        "occurred_at": _iso(document.created_at),
        "title": document.original_filename,
        "content": document.original_filename,
    }


def _render_calendar_event(session: Session, event_id: str) -> dict:
    event = session.get(CalendarEventCache, event_id)
    if event is None:
        raise _NotIndexable
    occurred = event.start_datetime or (
        datetime.combine(event.start_date, datetime.min.time(), tzinfo=timezone.utc) if event.start_date else event.fetched_at
    )
    content_parts = [event.title, event.description, event.location]
    return {
        # Calendar events are always LIFE, by the same established
        # convention `briefing_service.py`/Mission Control already use,
        # never stored per-row on CalendarEventCache itself.
        "domain_slug": "life",
        "occurred_at": _iso(occurred),
        "title": event.title,
        "content": " ".join(p for p in content_parts if p),
    }


def _render_action_proposal(session: Session, proposal_id: str) -> dict:
    proposal = session.get(ActionProposal, proposal_id)
    if proposal is None:
        raise _NotIndexable
    title = proposal.capability_id.replace(".", " ").replace("_", " ")
    content_parts = [proposal.reason, proposal.expected_effect, proposal.error_summary]
    return {
        "domain_slug": _domain_slug(session, proposal.domain_id),
        "occurred_at": _iso(proposal.created_at),
        "title": title,
        "content": " ".join(p for p in content_parts if p),
    }


# A routine run is indexed as global (domain_slug=None), so it is visible
# wherever global results are allowed, including default Recall and every
# Research/Decision evidence search. Only sections whose structured
# `domain_slug` tag is in this allowlist may contribute text; BODY/MIND/
# PEOPLE sections (present only when Bernardo opted them into a routine)
# stay in the Routine Centre and never reach the index. Fail closed: a
# section with no tag, an unknown tag, or a run written before sections
# were tagged contributes nothing.
_INDEXABLE_ROUTINE_SECTION_DOMAINS = frozenset({"life", "path", "build"})


def _routine_output_text(output_json: str | None) -> str:
    """Extracts only the documented plain-text `lines[].text` values from
    a routine run's structured, deterministic `output_json`, never the
    raw shape/keys, and safe against any malformed/unexpected JSON. Only
    sections tagged with an allowlisted domain are included (see
    `_INDEXABLE_ROUTINE_SECTION_DOMAINS`)."""
    if not output_json:
        return ""
    try:
        data = json.loads(output_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    texts: list[str] = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if section.get("domain_slug") not in _INDEXABLE_ROUTINE_SECTION_DOMAINS:
            continue
        if isinstance(section.get("title"), str):
            texts.append(section["title"])
        for line in section.get("lines") or []:
            if isinstance(line, dict) and isinstance(line.get("text"), str):
                texts.append(line["text"])
    return " ".join(texts)


def _render_routine_run(session: Session, run_id: str) -> dict:
    run = session.get(RoutineRun, run_id)
    if run is None:
        raise _NotIndexable
    title = run.routine_type.replace("_", " ").title()
    content = " ".join(p for p in (run.reason, _routine_output_text(run.output_json)) if p)
    return {
        # A routine run has no single owning domain (it may touch several
        # selected domains), so it is classified global/system.
        "domain_slug": None,
        "occurred_at": _iso(run.started_at),
        "title": title,
        "content": content or title,
    }


def _render_mission_control_session(session: Session, focus_session_id: str) -> dict:
    focus = session.get(FocusSession, focus_session_id)
    if focus is None:
        raise _NotIndexable
    content_parts = [focus.source_title_snapshot, focus.completion_note, focus.what_changed_note]
    return {
        "domain_slug": _domain_slug(session, focus.domain_id),
        "occurred_at": _iso(focus.started_at) or _iso(focus.created_at),
        "title": focus.title,
        "content": " ".join(p for p in content_parts if p) or focus.title,
    }


def _render_decision(session: Session, decision_id: str) -> dict:
    """Indexes the decision's title, active option names, the final
    rationale (Bernardo's words, never the model critique), open
    assumptions/risks and outcome-review lessons. Decisions are indexed
    at every status, since abandoned or superseded ones are still history
    worth finding, and they are never hard-deleted."""
    decision = session.get(Decision, decision_id)
    if decision is None:
        raise _NotIndexable

    option_names = [
        row[0]
        for row in session.execute(
            text("SELECT name FROM decision_options WHERE decision_id = :d AND status != 'eliminated' ORDER BY rank"),
            {"d": decision_id},
        ).all()
    ]

    latest_final = (
        session.query(DecisionFinalVersion)
        .filter(DecisionFinalVersion.decision_id == decision_id)
        .order_by(DecisionFinalVersion.version_number.desc())
        .first()
    )
    rationale = latest_final.rationale if latest_final else None

    factor_rows = (
        session.query(DecisionFactor)
        .filter(DecisionFactor.decision_id == decision_id, DecisionFactor.kind.in_(("assumption", "risk")))
        .all()
    )
    factor_texts = [f.content for f in factor_rows]

    outcome_texts: list[str] = []
    if latest_final:
        outcome = (
            session.query(DecisionOutcomeReview)
            .filter(DecisionOutcomeReview.decision_final_version_id == latest_final.id)
            .order_by(DecisionOutcomeReview.reviewed_at.desc())
            .first()
        )
        if outcome is not None:
            outcome_texts = [t for t in (outcome.what_happened, outcome.lessons_learned) if t]

    content_parts = [*option_names, rationale, *factor_texts, *outcome_texts]
    return {
        "domain_slug": _domain_slug(session, decision.domain_id),
        "occurred_at": _iso(decision.updated_at),
        "title": decision.title,
        "content": " ".join(p for p in content_parts if p) or decision.title,
    }


_RENDERERS = {
    "conversation": _render_conversation,
    "message": _render_message,
    "structured_record": _render_structured_record,
    "domain_summary": _render_domain_summary,
    "document": _render_document,
    "calendar_event": _render_calendar_event,
    "action_proposal": _render_action_proposal,
    "routine_run": _render_routine_run,
    "mission_control_session": _render_mission_control_session,
    "decision": _render_decision,
}


def sync_recall(session: Session, source_type: str, source_id: str) -> bool:
    """Re-derives and upserts (or removes, if no longer indexable) exactly
    one recall row from the real source row. Call this after every
    create/update/archive of a recall-eligible row; see the module
    docstring for why this single function safely covers all three.
    Returns True if a row was (re-)indexed, False if it was removed/
    skipped as not currently indexable."""
    renderer = _RENDERERS.get(source_type)
    if renderer is None:
        raise ValueError(f"Unknown recall source_type: {source_type!r}")
    if not _recall_fts_table_exists(session):
        return False
    _delete_recall_rows(session, source_type, source_id)
    try:
        fields = renderer(session, source_id)
    except _NotIndexable:
        return False
    _insert_recall_row(session, source_type=source_type, source_id=source_id, **fields)
    return True


def remove_recall(session: Session, source_type: str, source_id: str) -> None:
    """For a genuine hard delete (the source row itself is gone): a
    thin, explicitly-named wrapper so call sites read as "this was
    deleted", not "this happened to fail re-indexing"."""
    if not _recall_fts_table_exists(session):
        return
    _delete_recall_rows(session, source_type, source_id)


def rebuild_recall_index(session: Session) -> int:
    """Drops and repopulates the entire recall index from current
    ground-truth tables. This is the backfill path for an installation upgrading
    from before migration 0016, and the manual repair path if the index
    is ever suspected stale or corrupt. Safe to call at any time; never
    touches `memory_fts`/`document_fts`, which remain independently
    rebuildable via their own existing `rebuild_fts()`/
    `rebuild_document_fts()`."""
    session.execute(text("DELETE FROM recall_fts"))
    count = 0

    def _sync_all(source_type: str, id_sql: str) -> None:
        nonlocal count
        for (row_id,) in session.execute(text(id_sql)).all():
            if sync_recall(session, source_type, row_id):
                count += 1

    _sync_all("conversation", "SELECT id FROM conversations WHERE archived_at IS NULL")
    _sync_all(
        "message",
        "SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE c.archived_at IS NULL",
    )
    _sync_all("structured_record", "SELECT id FROM structured_records WHERE archived_at IS NULL")
    _sync_all("domain_summary", "SELECT id FROM domains")
    _sync_all("document", "SELECT id FROM documents WHERE status = 'ready'")
    _sync_all("calendar_event", "SELECT id FROM calendar_event_cache")
    _sync_all("action_proposal", "SELECT id FROM action_proposals")
    _sync_all("routine_run", "SELECT id FROM routine_runs")
    _sync_all("mission_control_session", "SELECT id FROM focus_sessions")
    _sync_all("decision", "SELECT id FROM decisions")

    session.commit()
    return count
