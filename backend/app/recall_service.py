"""Phase 12D: Unified Recall and Provenance — deterministic local search
across every domain, reusing FTS5 wherever it already exists rather than
building a second index over the same content.

Hard rules enforced by construction here (mirrors CLAUDE.md's Recall
requirements and the model-free discipline Phase 12A-12C already
established):

  * No model call, no Hermes call, anywhere in this module.
  * A search never mutates application state — every function here is
    read-only except `rebuild_recall_index` (an explicit repair action,
    never invoked by an ordinary search).
  * `search()` merges three independently-scored FTS families —
    `memory_fts` (unchanged, `app.fts_service`), `document_fts`
    (unchanged, `app.document_fts_service`), and the new `recall_fts`
    (`app.recall_index_service`) — never a fourth, duplicated copy of
    already-indexed content. Raw bm25 scores are not comparable across
    tables with different corpora, so each family's scores are min-max
    normalized to a 0-1 "relevance" value before combining — see
    `_normalize_family` for the exact formula.
  * BODY/MIND/PEOPLE are excluded from every default (no explicit
    `domain_slugs` argument) — the only way sensitive-domain content can
    ever appear is an explicit, caller-supplied domain list, mirroring
    Phase 12A/12B/12C's identical structural rule for the Home briefing.
  * One broken FTS family must never zero out every other family's
    results — each family query is independently wrapped, and a failure
    is reported truthfully in `RecallSearchResult.partial_failures`
    rather than silently swallowed or crashing the whole search.
  * Every result's real source row is re-resolved fresh at read time
    (`_resolve_availability`) — a result is never trusted to still be
    accurate just because it matched in the index; a source that has
    since been archived/deleted/superseded is reported as genuinely
    "unavailable" rather than silently kept or fabricated.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.document_fts_service import search_document_fts
from app.fts_service import sanitize_fts_query, search_memory_fts
from app.models import Conversation, Domain, Message
from app.models_actions import ActionProposal
from app.models_decisions import Decision
from app.models_integrations import CalendarEventCache, Document, DocumentChunk
from app.models_memory import MemoryItem, StructuredRecord
from app.models_mission_control import FocusSession
from app.models_routines import RoutineRun
from app.recall_index_service import (
    _RENDERERS,
    RECALL_SOURCE_TYPES,
    _NotIndexable,
    rebuild_recall_index,
)

# The complete public source-type vocabulary — RECALL_SOURCE_TYPES (the
# nine indexed directly into recall_fts) plus the two that keep using
# their own pre-existing, unduplicated FTS tables.
ALL_RECALL_SOURCE_TYPES = (*RECALL_SOURCE_TYPES, "memory_item", "document_chunk")

# The only domains ever included when a search omits an explicit domain
# list — CLAUDE.md's own privacy rule for the Home briefing, applied
# identically here: BODY/MIND/PEOPLE always require explicit opt-in.
DEFAULT_DOMAIN_SLUGS = ("life", "path", "build")
SENSITIVE_DOMAIN_SLUGS = ("body", "mind", "people")

RECALL_MAX_LIMIT = 50
RECALL_MAX_OFFSET_PLUS_LIMIT = 500
_FAMILY_FETCH_CAP = 200

# A bounded, documented secondary signal — see the module docstring and
# `_score` below for why this can only ever break a near-tie, never
# override a real relevance difference.
_EXACT_TITLE_MATCH_BONUS = 0.5
_CURRENT_DOMAIN_BONUS = 0.1
_RECENCY_BONUS_MAX = 0.05
_RECENCY_HALF_LIFE_DAYS = 365.0

_HIGHLIGHT_TOKEN_PATTERN_CACHE: dict[str, re.Pattern] = {}


@dataclass(frozen=True)
class RecallHit:
    source_type: str
    source_id: str
    domain_slug: str | None
    occurred_at: str | None
    title: str
    content: str
    raw_score: float


@dataclass(frozen=True)
class RecallResult:
    source_type: str
    source_id: str
    domain_slug: str | None
    title: str
    snippet_html: str
    occurred_at: str | None
    link_target: str | None
    available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class RecallSearchResult:
    query: str
    results: list[RecallResult]
    total_considered: int
    limit: int
    offset: int
    has_more: bool
    partial_failures: list[str] = field(default_factory=list)


def _resolve_domain_slugs(domain_slugs: list[str] | None) -> tuple[str, ...]:
    if domain_slugs is None:
        return DEFAULT_DOMAIN_SLUGS
    # An explicit but empty list is a real, deliberate "no domain
    # allowed" request (e.g. "only global/system results") — never
    # silently widened back out to the default set.
    return tuple(domain_slugs)


def _domain_ids_for_slugs_safe(session: Session, slugs: tuple[str, ...]) -> list[str]:
    """Builds explicit named placeholders rather than relying on
    driver-specific tuple binding for `IN :slugs`."""
    if not slugs:
        return []
    placeholders = ", ".join(f":slug_{i}" for i in range(len(slugs)))
    params = {f"slug_{i}": slug for i, slug in enumerate(slugs)}
    rows = session.execute(text(f"SELECT id FROM domains WHERE slug IN ({placeholders})"), params)
    return [row[0] for row in rows.all()]


def _normalize_family(scores: list[float]) -> list[float]:
    """Min-max normalizes a family's raw bm25 scores (lower = more
    relevant, SQLite FTS5's convention) into a 0-1 relevance value where
    1.0 is the best match in that family's own result set. A single
    result, or a family where every score ties, normalizes to 1.0 for
    all — there is no meaningful spread to express."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return [1.0 for _ in scores]
    return [1.0 - (s - lo) / (hi - lo) for s in scores]


def _days_since(occurred_at: str | None, now: datetime) -> float | None:
    if not occurred_at:
        return None
    try:
        parsed = datetime.fromisoformat(occurred_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds() / 86400.0)


def _score(hit: RecallHit, relevance: float, query_lower: str, current_domain: str | None, now: datetime) -> float:
    total = relevance
    if query_lower and query_lower in hit.title.lower():
        total += _EXACT_TITLE_MATCH_BONUS
    if current_domain and hit.domain_slug == current_domain:
        total += _CURRENT_DOMAIN_BONUS
    days = _days_since(hit.occurred_at, now)
    if days is not None:
        total += _RECENCY_BONUS_MAX * (_RECENCY_HALF_LIFE_DAYS / (_RECENCY_HALF_LIFE_DAYS + days))
    return total


def _highlight_pattern(query: str) -> re.Pattern:
    cached = _HIGHLIGHT_TOKEN_PATTERN_CACHE.get(query)
    if cached is not None:
        return cached
    tokens = sorted({re.escape(t) for t in query.split() if t}, key=len, reverse=True)
    pattern = re.compile("|".join(tokens), re.IGNORECASE) if tokens else re.compile(r"(?!x)x")
    if len(_HIGHLIGHT_TOKEN_PATTERN_CACHE) > 256:
        _HIGHLIGHT_TOKEN_PATTERN_CACHE.clear()
    _HIGHLIGHT_TOKEN_PATTERN_CACHE[query] = pattern
    return pattern


def make_snippet_html(content: str, query: str, *, radius: int = 80, max_len: int = 220) -> str:
    """Escapes `content` first (so nothing in retrieved document/message
    text can ever inject markup — a document's own text is data, never
    instructions or HTML, no matter what it contains), then wraps
    plain-text query token matches in `<mark>` — the highlighting always
    operates on the same escaped string it returns, so it can never
    reopen an HTML-injection path the initial escape just closed."""
    content = content or ""
    pattern = _highlight_pattern(query)
    match = pattern.search(content)
    if match:
        start = max(0, match.start() - radius)
        end = min(len(content), match.end() + radius)
        excerpt = content[start:end]
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(content) else ""
    else:
        excerpt = content[:max_len]
        prefix = ""
        suffix = "…" if len(content) > max_len else ""

    escaped = html.escape(excerpt)

    def _wrap(m: re.Match) -> str:
        return f"<mark>{html.escape(m.group(0))}</mark>"

    highlighted = pattern.sub(_wrap, escaped) if match else escaped
    return f"{prefix}{highlighted}{suffix}"


_LINK_TARGETS = {
    "conversation": lambda domain_slug: f"domain:{domain_slug}" if domain_slug else "general",
    "message": lambda domain_slug: f"domain:{domain_slug}" if domain_slug else "general",
    "memory_item": lambda _domain_slug: "memory_centre",
    "structured_record": lambda domain_slug: f"domain:{domain_slug}" if domain_slug else None,
    "domain_summary": lambda domain_slug: f"domain:{domain_slug}" if domain_slug else None,
    "document": lambda _domain_slug: "integrations_centre",
    "document_chunk": lambda _domain_slug: "integrations_centre",
    "calendar_event": lambda _domain_slug: "integrations_centre",
    "action_proposal": lambda _domain_slug: "actions_centre",
    "routine_run": lambda _domain_slug: "routine_centre",
    "mission_control_session": lambda _domain_slug: "home",
    "decision": lambda _domain_slug: "decision_centre",
}


def _link_target(source_type: str, domain_slug: str | None) -> str | None:
    builder = _LINK_TARGETS.get(source_type)
    return builder(domain_slug) if builder else None


def _resolve_availability(session: Session, hit: RecallHit) -> tuple[bool, str | None]:
    """Re-checks the real source row fresh, independent of whatever the
    index currently says — the index is a cache, never the truth."""
    try:
        if hit.source_type == "conversation":
            row = session.get(Conversation, hit.source_id)
            ok = row is not None and row.archived_at is None
        elif hit.source_type == "message":
            row = session.get(Message, hit.source_id)
            ok = row is not None and row.conversation is not None and row.conversation.archived_at is None
        elif hit.source_type == "memory_item":
            row = session.get(MemoryItem, hit.source_id)
            ok = row is not None and row.status == "active"
        elif hit.source_type == "structured_record":
            row = session.get(StructuredRecord, hit.source_id)
            ok = row is not None and row.archived_at is None
        elif hit.source_type == "domain_summary":
            row = session.get(Domain, hit.source_id)
            ok = row is not None
        elif hit.source_type in ("document", "document_chunk"):
            document_id = hit.source_id if hit.source_type == "document" else None
            if hit.source_type == "document_chunk":
                chunk = session.get(DocumentChunk, hit.source_id)
                document_id = chunk.document_id if chunk else None
            row = session.get(Document, document_id) if document_id else None
            ok = row is not None and row.status == "ready"
        elif hit.source_type == "calendar_event":
            row = session.get(CalendarEventCache, hit.source_id)
            ok = row is not None
        elif hit.source_type == "action_proposal":
            row = session.get(ActionProposal, hit.source_id)
            ok = row is not None
        elif hit.source_type == "routine_run":
            row = session.get(RoutineRun, hit.source_id)
            ok = row is not None
        elif hit.source_type == "mission_control_session":
            row = session.get(FocusSession, hit.source_id)
            ok = row is not None
        elif hit.source_type == "decision":
            # Always available once created — a Decision is never hard-
            # deleted (see app.decision_service and CLAUDE.md's "do not
            # silently delete user-authored decisions"), and unlike an
            # archived MemoryItem, "superseded"/"abandoned" is a real
            # historical outcome this feature is built to keep auditable,
            # not retired content — see recall_index_service._render_decision.
            row = session.get(Decision, hit.source_id)
            ok = row is not None
        else:
            ok = False
    except Exception:
        # A resolution failure is truthfully "unavailable", never a 500 —
        # this is a read-only re-check, not a search-blocking dependency.
        ok = False
    return (True, None) if ok else (False, "Source unavailable")


def resolve_source_snapshot(session: Session, source_type: str, source_id: str) -> dict | None:
    """A freshly-resolved, server-side display snapshot (`domain_slug`/
    `occurred_at`/`title`/`content`) for one Recall-eligible source —
    exactly the same rendering `recall_index_service` uses to populate
    `recall_fts`, exposed here so anything that needs to freeze a
    citation-safe snapshot of a source (Phase 12E Research evidence) reuses
    this single resolution path instead of re-deriving it. Returns None if
    the source does not exist or is not currently indexable/visible — never
    trusts a caller-supplied title/content for anything. Not itself a
    second search engine: this resolves exactly one already-known
    source_type/source_id pair, never queries or ranks anything."""
    if source_type in RECALL_SOURCE_TYPES:
        renderer = _RENDERERS.get(source_type)
        if renderer is None:
            return None
        try:
            return renderer(session, source_id)
        except _NotIndexable:
            return None
    if source_type == "memory_item":
        item = session.get(MemoryItem, source_id)
        if item is None or item.status != "active" or item.current_version is None:
            return None
        domain_slug = None
        if item.domain_id:
            domain = session.get(Domain, item.domain_id)
            domain_slug = domain.slug if domain else None
        return {
            "domain_slug": domain_slug,
            "occurred_at": item.current_version.created_at.isoformat()
            if item.current_version.created_at
            else None,
            "title": item.current_version.title,
            "content": item.current_version.content,
        }
    if source_type == "document_chunk":
        chunk = session.get(DocumentChunk, source_id)
        if chunk is None:
            return None
        document = session.get(Document, chunk.document_id)
        if document is None or document.status != "ready":
            return None
        domain = session.get(Domain, document.domain_id)
        return {
            "domain_slug": domain.slug if domain else None,
            "occurred_at": document.created_at.isoformat() if document.created_at else None,
            "title": document.original_filename,
            "content": chunk.content,
        }
    return None


def resolve_availability(session: Session, source_type: str, source_id: str) -> tuple[bool, str | None]:
    """Public entry point for the exact same fresh, re-checked-at-read-time
    availability rule `search()` applies to every result — reused by
    Research so a citation's "current availability state" is never trusted
    from a frozen snapshot."""
    hit = RecallHit(
        source_type=source_type, source_id=source_id, domain_slug=None, occurred_at=None, title="", content="",
        raw_score=0.0,
    )
    return _resolve_availability(session, hit)


def resolve_link_target(source_type: str, domain_slug: str | None) -> str | None:
    """Public entry point for the same source_type/domain_slug -> UI
    navigation-target mapping `search()` results already carry — reused by
    Research's own citation records rather than re-declaring a second copy
    of this table."""
    return _link_target(source_type, domain_slug)


def search(
    session: Session,
    query: str,
    *,
    domain_slugs: list[str] | None = None,
    source_types: list[str] | None = None,
    include_global: bool = True,
    current_domain: str | None = None,
    limit: int = 20,
    offset: int = 0,
    now: datetime | None = None,
) -> RecallSearchResult:
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(RECALL_MAX_LIMIT, limit))
    offset = max(0, offset)
    if offset + limit > RECALL_MAX_OFFSET_PLUS_LIMIT:
        offset = max(0, RECALL_MAX_OFFSET_PLUS_LIMIT - limit)

    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return RecallSearchResult(query=query, results=[], total_considered=0, limit=limit, offset=offset, has_more=False)

    allowed_domains = _resolve_domain_slugs(domain_slugs)
    allowed_types = set(source_types) if source_types else set(ALL_RECALL_SOURCE_TYPES)
    allowed_types &= set(ALL_RECALL_SOURCE_TYPES)
    fetch_cap = min(_FAMILY_FETCH_CAP, offset + limit + 50)

    hits: list[RecallHit] = []
    partial_failures: list[str] = []

    if "memory_item" in allowed_types:
        try:
            domain_ids = _domain_ids_for_slugs_safe(session, allowed_domains)
            memory_hits = search_memory_fts(
                session, query, domain_ids=domain_ids or None, include_global=include_global, limit=fetch_cap
            )
            for memory_item_id, score in memory_hits:
                item = session.get(MemoryItem, memory_item_id)
                if item is None or item.status != "active" or item.current_version is None:
                    continue
                domain_slug = None
                if item.domain_id:
                    domain = session.get(Domain, item.domain_id)
                    domain_slug = domain.slug if domain else None
                hits.append(
                    RecallHit(
                        source_type="memory_item",
                        source_id=memory_item_id,
                        domain_slug=domain_slug,
                        occurred_at=item.current_version.created_at.isoformat()
                        if item.current_version.created_at
                        else None,
                        title=item.current_version.title,
                        content=item.current_version.content,
                        raw_score=score,
                    )
                )
        except Exception:
            partial_failures.append("memory_item")

    if "document_chunk" in allowed_types:
        try:
            domain_ids = _domain_ids_for_slugs_safe(session, allowed_domains)
            doc_hits = search_document_fts(session, query, domain_ids=domain_ids or None, limit=fetch_cap)
            for document_id, chunk_id, score in doc_hits:
                chunk = session.get(DocumentChunk, chunk_id)
                document = session.get(Document, document_id)
                if chunk is None or document is None or document.status != "ready":
                    continue
                domain = session.get(Domain, document.domain_id)
                hits.append(
                    RecallHit(
                        source_type="document_chunk",
                        source_id=chunk_id,
                        domain_slug=domain.slug if domain else None,
                        occurred_at=document.created_at.isoformat() if document.created_at else None,
                        title=document.original_filename,
                        content=chunk.content,
                        raw_score=score,
                    )
                )
        except Exception:
            partial_failures.append("document_chunk")

    recall_types = allowed_types & set(RECALL_SOURCE_TYPES)
    if recall_types:
        try:
            hits.extend(_search_recall_fts(session, safe_query, allowed_domains, include_global, recall_types, fetch_cap))
        except Exception:
            partial_failures.append("recall_fts")

    # Normalize each family's raw scores independently before combining —
    # see the module docstring for why raw bm25 isn't comparable across
    # differently-shaped FTS tables.
    by_family: dict[str, list[int]] = {}
    for i, hit in enumerate(hits):
        family = "memory_item" if hit.source_type == "memory_item" else (
            "document_chunk" if hit.source_type == "document_chunk" else "recall_fts"
        )
        by_family.setdefault(family, []).append(i)

    relevance = [0.0] * len(hits)
    for indices in by_family.values():
        normalized = _normalize_family([hits[i].raw_score for i in indices])
        for idx, value in zip(indices, normalized):
            relevance[idx] = value

    query_lower = query.strip().lower()
    scored = [
        (_score(hit, relevance[i], query_lower, current_domain, now), hit) for i, hit in enumerate(hits)
    ]
    scored.sort(key=lambda pair: (-pair[0], pair[1].source_type, pair[1].source_id))

    total_considered = len(scored)
    page = scored[offset : offset + limit]

    results: list[RecallResult] = []
    for _score_value, hit in page:
        available, reason = _resolve_availability(session, hit)
        results.append(
            RecallResult(
                source_type=hit.source_type,
                source_id=hit.source_id,
                domain_slug=hit.domain_slug,
                title=hit.title,
                snippet_html=make_snippet_html(hit.content, query),
                occurred_at=hit.occurred_at,
                link_target=_link_target(hit.source_type, hit.domain_slug),
                available=available,
                unavailable_reason=reason,
            )
        )

    return RecallSearchResult(
        query=query,
        results=results,
        total_considered=total_considered,
        limit=limit,
        offset=offset,
        has_more=offset + limit < total_considered,
        partial_failures=partial_failures,
    )


def _search_recall_fts(
    session: Session,
    safe_query: str,
    allowed_domains: tuple[str, ...],
    include_global: bool,
    source_types: set[str],
    limit: int,
) -> list[RecallHit]:
    params: dict = {"query": safe_query, "limit": limit}
    clauses = []

    type_placeholders = ", ".join(f":type_{i}" for i in range(len(source_types)))
    for i, t in enumerate(source_types):
        params[f"type_{i}"] = t
    clauses.append(f"source_type IN ({type_placeholders})")

    domain_clause = "domain_slug IS NULL" if include_global else "1=0"
    if allowed_domains:
        placeholders = ", ".join(f":domain_{i}" for i in range(len(allowed_domains)))
        for i, slug in enumerate(allowed_domains):
            params[f"domain_{i}"] = slug
        domain_clause = f"({domain_clause} OR domain_slug IN ({placeholders}))"
    clauses.append(domain_clause)

    where_extra = " AND " + " AND ".join(clauses) if clauses else ""
    sql = text(
        f"""
        SELECT source_type, source_id, domain_slug, occurred_at, title, content, bm25(recall_fts) AS score
        FROM recall_fts
        WHERE recall_fts MATCH :query
        {where_extra}
        ORDER BY score
        LIMIT :limit
        """
    )
    rows = session.execute(sql, params).fetchall()
    return [
        RecallHit(
            source_type=row[0],
            source_id=row[1],
            domain_slug=row[2],
            occurred_at=row[3],
            title=row[4],
            content=row[5],
            raw_score=row[6],
        )
        for row in rows
    ]


__all__ = [
    "ALL_RECALL_SOURCE_TYPES",
    "DEFAULT_DOMAIN_SLUGS",
    "SENSITIVE_DOMAIN_SLUGS",
    "RECALL_MAX_LIMIT",
    "RecallResult",
    "RecallSearchResult",
    "make_snippet_html",
    "search",
    "rebuild_recall_index",
    "resolve_source_snapshot",
    "resolve_availability",
    "resolve_link_target",
]
