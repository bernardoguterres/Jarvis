"""Phase 12D: Unified Recall and Provenance HTTP surface. Deterministic
local search only — never a model call, never a mutation. `POST /rebuild`
is the one exception to "read-only": an explicit, user-triggered repair
action, not something an ordinary search ever calls itself."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import recall_service
from app.deps import get_db
from app.schemas_recall import RecallRebuildRead, RecallResultRead, RecallSearchRead

router = APIRouter(tags=["recall"])


@router.get("/api/recall/search", response_model=RecallSearchRead)
def search_recall(
    q: str = Query(default=""),
    domains: str | None = Query(default=None, description="Comma-separated domain slugs; omit for the default LIFE/PATH/BUILD set"),
    source_types: str | None = Query(default=None, description="Comma-separated source types; omit for all"),
    include_global: bool = Query(default=True),
    current_domain: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=recall_service.RECALL_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RecallSearchRead:
    domain_slugs = [s.strip() for s in domains.split(",") if s.strip()] if domains is not None else None
    types = [s.strip() for s in source_types.split(",") if s.strip()] if source_types is not None else None
    result = recall_service.search(
        db,
        q,
        domain_slugs=domain_slugs,
        source_types=types,
        include_global=include_global,
        current_domain=current_domain,
        limit=limit,
        offset=offset,
    )
    return RecallSearchRead(
        query=result.query,
        results=[
            RecallResultRead(
                source_type=r.source_type,
                source_id=r.source_id,
                domain_slug=r.domain_slug,
                title=r.title,
                snippet_html=r.snippet_html,
                occurred_at=r.occurred_at,
                link_target=r.link_target,
                available=r.available,
                unavailable_reason=r.unavailable_reason,
            )
            for r in result.results
        ],
        total_considered=result.total_considered,
        limit=result.limit,
        offset=result.offset,
        has_more=result.has_more,
        partial_failures=result.partial_failures,
    )


@router.post("/api/recall/rebuild", response_model=RecallRebuildRead)
def rebuild_recall(db: Session = Depends(get_db)) -> RecallRebuildRead:
    count = recall_service.rebuild_recall_index(db)
    return RecallRebuildRead(indexed_count=count)
