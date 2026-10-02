from __future__ import annotations

from sqlalchemy.orm import Session

from app import document_service
from app.config import Settings
from app.document_fts_service import search_document_fts
from app.models import Domain


def test_none_domain_ids_searches_every_domain_by_default(
    db_session: Session, memory_settings: Settings
) -> None:
    mind = db_session.query(Domain).filter_by(slug="mind").one()
    document_service.import_document(
        db_session, memory_settings, domain_id=mind.id, original_filename="diary.txt",
        data=b"Feeling anxious about the relationship.",
    )
    hits = search_document_fts(db_session, "anxious", domain_ids=None)
    assert len(hits) == 1


def test_explicit_empty_domain_ids_matches_nothing(
    db_session: Session, memory_settings: Settings
) -> None:
    """Regression: every document belongs to exactly one domain (there is
    no "global" document), so an explicit empty scope must match zero
    documents, never silently falling back to "no filter" and leaking MIND/
    PEOPLE document content into an unrelated context."""
    mind = db_session.query(Domain).filter_by(slug="mind").one()
    document_service.import_document(
        db_session, memory_settings, domain_id=mind.id, original_filename="diary.txt",
        data=b"Feeling anxious about the relationship.",
    )
    hits = search_document_fts(db_session, "anxious", domain_ids=[])
    assert hits == []


def test_named_domain_ids_still_scope_correctly(
    db_session: Session, memory_settings: Settings
) -> None:
    mind = db_session.query(Domain).filter_by(slug="mind").one()
    life = db_session.query(Domain).filter_by(slug="life").one()
    document_service.import_document(
        db_session, memory_settings, domain_id=mind.id, original_filename="diary.txt",
        data=b"Feeling anxious about the relationship.",
    )
    assert search_document_fts(db_session, "anxious", domain_ids=[life.id]) == []
    assert len(search_document_fts(db_session, "anxious", domain_ids=[mind.id])) == 1
