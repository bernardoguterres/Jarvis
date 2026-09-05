"""Derived, rebuildable FTS5 index over imported document chunk text.

Never authoritative — document_chunks is the source of truth. Mirrors
app/fts_service.py's pattern for memory (see D31 there for why OR, not
AND, joins tokens)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.fts_service import sanitize_fts_query
from app.models_integrations import Document, DocumentChunk


def upsert_document_chunk_fts(session: Session, chunk: DocumentChunk, domain_id: str) -> None:
    session.execute(text("DELETE FROM document_fts WHERE chunk_id = :id"), {"id": chunk.id})
    session.execute(
        text(
            "INSERT INTO document_fts (document_id, chunk_id, domain_id, content) "
            "VALUES (:document_id, :chunk_id, :domain_id, :content)"
        ),
        {"document_id": chunk.document_id, "chunk_id": chunk.id, "domain_id": domain_id, "content": chunk.content},
    )


def remove_document_fts(session: Session, document_id: str) -> None:
    session.execute(text("DELETE FROM document_fts WHERE document_id = :id"), {"id": document_id})


def rebuild_document_fts(session: Session) -> int:
    session.execute(text("DELETE FROM document_fts"))
    count = 0
    for document in session.query(Document).filter(Document.status == "ready").all():
        for chunk in document.chunks:
            session.execute(
                text(
                    "INSERT INTO document_fts (document_id, chunk_id, domain_id, content) "
                    "VALUES (:document_id, :chunk_id, :domain_id, :content)"
                ),
                {
                    "document_id": document.id,
                    "chunk_id": chunk.id,
                    "domain_id": document.domain_id,
                    "content": chunk.content,
                },
            )
            count += 1
    session.commit()
    return count


def search_document_fts(
    session: Session, query: str, *, domain_ids: list[str] | None = None, limit: int = 10
) -> list[tuple[str, str, float]]:
    """Returns (document_id, chunk_id, bm25_score) tuples ordered by relevance."""
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []

    params: dict = {"query": safe_query, "limit": limit}
    where_scope = ""
    if domain_ids:
        placeholders = ", ".join(f":domain_{i}" for i in range(len(domain_ids)))
        for i, domain_id in enumerate(domain_ids):
            params[f"domain_{i}"] = domain_id
        where_scope = f"AND domain_id IN ({placeholders})"

    sql = text(
        f"""
        SELECT document_id, chunk_id, bm25(document_fts) AS score
        FROM document_fts
        WHERE document_fts MATCH :query
        {where_scope}
        ORDER BY score
        LIMIT :limit
        """
    )
    try:
        rows = session.execute(sql, params).fetchall()
    except Exception:
        return []
    return [(row[0], row[1], row[2]) for row in rows]
