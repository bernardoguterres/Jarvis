from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import memory_service
from app.fts_service import rebuild_fts, sanitize_fts_query, search_memory_fts
from app.models import Domain


def _body_id(session: Session) -> str:
    return session.query(Domain).filter_by(slug="body").one().id


def test_creating_memory_indexes_it_for_search(db_session: Session) -> None:
    body_id = _body_id(db_session)
    item = memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context",
        title="Knee issue", content="History of knee pain from running.",
    )
    hits = search_memory_fts(db_session, "knee", domain_ids=[body_id])
    assert item.id in [h[0] for h in hits]


def test_rebuild_repopulates_index_from_source(db_session: Session) -> None:
    body_id = _body_id(db_session)
    item = memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context",
        title="Knee issue", content="History of knee pain.",
    )
    db_session.execute(text("DELETE FROM memory_fts"))
    db_session.commit()
    assert search_memory_fts(db_session, "knee", domain_ids=[body_id]) == []

    count = rebuild_fts(db_session)
    assert count >= 1
    hits = search_memory_fts(db_session, "knee", domain_ids=[body_id])
    assert item.id in [h[0] for h in hits]


def test_archived_memory_not_in_rebuilt_index(db_session: Session) -> None:
    body_id = _body_id(db_session)
    item = memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context",
        title="Knee issue", content="History of knee pain.",
    )
    memory_service.archive_memory(db_session, item.id)
    rebuild_fts(db_session)
    hits = search_memory_fts(db_session, "knee", domain_ids=[body_id])
    assert item.id not in [h[0] for h in hits]


def test_punctuation_and_operators_do_not_raise(db_session: Session) -> None:
    body_id = _body_id(db_session)
    memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context",
        title="Knee issue", content="History of knee pain.",
    )
    dangerous_queries = [
        'knee AND OR NOT "unterminated',
        "knee* OR (fake",
        "col:value",
        "🦵 knee ünïcödé",
        '"""',
        "**()::",
    ]
    for q in dangerous_queries:
        # Must never raise — either returns hits or an empty list.
        result = search_memory_fts(db_session, q, domain_ids=[body_id])
        assert isinstance(result, list)


def test_sanitize_fts_query_produces_quoted_phrase_tokens() -> None:
    safe = sanitize_fts_query('knee AND "pain"')
    assert safe  # non-empty
    assert '"' in safe


def test_sanitize_empty_query_returns_empty_string() -> None:
    assert sanitize_fts_query("   ") == ""
    assert sanitize_fts_query("***:::") == ""


def test_lexical_relevance_orders_best_match_first(db_session: Session) -> None:
    body_id = _body_id(db_session)
    memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="health_context",
        title="Knee issue", content="Knee knee knee pain pain pain, very knee-focused note.",
    )
    memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="fact",
        title="Unrelated", content="Something about sleep schedule, mentions knee once in passing.",
    )
    hits = search_memory_fts(db_session, "knee", domain_ids=[body_id])
    assert len(hits) == 2
    # Lower bm25 score = more relevant; the knee-heavy memory should rank first.
    assert hits[0][1] <= hits[1][1]


def test_no_match_returns_empty_list_for_fallback(db_session: Session) -> None:
    body_id = _body_id(db_session)
    memory_service.create_memory(
        db_session, scope="domain", domain_id=body_id, kind="fact", title="T", content="unrelated content",
    )
    hits = search_memory_fts(db_session, "zzzznonexistentword", domain_ids=[body_id])
    assert hits == []
