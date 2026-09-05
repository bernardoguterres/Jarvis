"""Derived, rebuildable FTS5 index over active memory content.

The FTS table is never authoritative — memory_items/memory_versions are the
source of truth. This module is the only place that writes to or reads from
memory_fts, so keeping it in sync (or rebuilding it from scratch) never
depends on remembering to do so elsewhere.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models_memory import MemoryItem

# FTS5 query syntax treats these as operators/punctuation with special
# meaning (AND/OR/NOT, column filters, phrase quotes, prefix *, grouping).
# A raw user query containing them can otherwise raise "fts5: syntax error".
_FTS_SPECIAL_CHARS = re.compile(r'["^*:()]')


def sanitize_fts_query(raw_query: str) -> str:
    """Turns arbitrary user text into a safe FTS5 MATCH argument: every
    token is treated as a literal quoted phrase (so operators/punctuation/
    unusual Unicode in the input can never produce malformed FTS5 syntax),
    joined with OR (so a natural-language query matches documents containing
    ANY of its words, ranked by bm25 — FTS5's default between bare terms is
    AND, which would otherwise require every word, including "what"/"do"/
    "you", to appear in the same short memory and silently match nothing)."""
    tokens = [t for t in raw_query.strip().split() if t]
    if not tokens:
        return ""
    safe_tokens = []
    for token in tokens:
        cleaned = _FTS_SPECIAL_CHARS.sub(" ", token).strip()
        if not cleaned:
            continue
        escaped = cleaned.replace('"', '""')
        safe_tokens.append(f'"{escaped}"')
    return " OR ".join(safe_tokens)


def upsert_memory_fts(session: Session, memory_item: MemoryItem, title: str, content: str) -> None:
    session.execute(
        text("DELETE FROM memory_fts WHERE memory_item_id = :id"), {"id": memory_item.id}
    )
    if memory_item.status != "active":
        return
    session.execute(
        text(
            "INSERT INTO memory_fts (memory_item_id, scope, domain_id, title, content) "
            "VALUES (:id, :scope, :domain_id, :title, :content)"
        ),
        {
            "id": memory_item.id,
            "scope": memory_item.scope,
            "domain_id": memory_item.domain_id,
            "title": title,
            "content": content,
        },
    )


def remove_memory_fts(session: Session, memory_item_id: str) -> None:
    session.execute(text("DELETE FROM memory_fts WHERE memory_item_id = :id"), {"id": memory_item_id})


def rebuild_fts(session: Session) -> int:
    """Drops and repopulates the entire FTS index from current
    memory_items/memory_versions. Safe to call any time (e.g. after a
    restore, or if the index is ever suspected corrupt)."""
    session.execute(text("DELETE FROM memory_fts"))

    active_items = (
        session.query(MemoryItem)
        .filter(MemoryItem.status == "active", MemoryItem.current_version_id.isnot(None))
        .all()
    )
    count = 0
    for item in active_items:
        version = item.current_version
        if version is None:
            continue
        session.execute(
            text(
                "INSERT INTO memory_fts (memory_item_id, scope, domain_id, title, content) "
                "VALUES (:id, :scope, :domain_id, :title, :content)"
            ),
            {
                "id": item.id,
                "scope": item.scope,
                "domain_id": item.domain_id,
                "title": version.title,
                "content": version.content,
            },
        )
        count += 1
    session.commit()
    return count


def search_memory_fts(
    session: Session,
    query: str,
    *,
    domain_ids: list[str] | None = None,
    include_global: bool = True,
    limit: int = 20,
) -> list[tuple[str, float]]:
    """Returns (memory_item_id, bm25_score) pairs ordered by relevance
    (lower bm25 = more relevant). Empty list if the query has no usable
    tokens or matches nothing — callers fall back to importance/recency."""
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []

    # No domain filter at all means "search everything" (every domain plus
    # global) — include_global only matters once a domain filter narrows the
    # scope, where it decides whether global memories are added back in.
    scope_clauses = []
    params: dict = {"query": safe_query, "limit": limit}
    if domain_ids:
        placeholders = ", ".join(f":domain_{i}" for i in range(len(domain_ids)))
        for i, domain_id in enumerate(domain_ids):
            params[f"domain_{i}"] = domain_id
        scope_clause = f"domain_id IN ({placeholders})"
        if include_global:
            scope_clause = f"({scope_clause} OR scope = 'global')"
        scope_clauses.append(scope_clause)

    where_scope = f"AND {' AND '.join(scope_clauses)}" if scope_clauses else ""

    sql = text(
        f"""
        SELECT memory_item_id, bm25(memory_fts) AS score
        FROM memory_fts
        WHERE memory_fts MATCH :query
        {where_scope}
        ORDER BY score
        LIMIT :limit
        """
    )
    try:
        rows = session.execute(sql, params).fetchall()
    except Exception:
        # Defense in depth: never let a malformed/unusual query 500 the turn.
        return []
    return [(row[0], row[1]) for row in rows]
