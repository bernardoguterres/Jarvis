"""Phase 12D: Unified Recall and Provenance — request/response models.
Never includes raw document/content beyond an already-escaped,
highlighted snippet — see `app.recall_service.make_snippet_html`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.recall_service import ALL_RECALL_SOURCE_TYPES

RecallSourceType = Literal[
    "conversation",
    "message",
    "memory_item",
    "structured_record",
    "domain_summary",
    "document",
    "document_chunk",
    "calendar_event",
    "action_proposal",
    "routine_run",
    "mission_control_session",
    "decision",
]
assert set(RecallSourceType.__args__) == set(ALL_RECALL_SOURCE_TYPES)

RecallDomainSlug = Literal["body", "build", "life", "mind", "path", "people"]


class RecallResultRead(BaseModel):
    source_type: RecallSourceType
    source_id: str
    domain_slug: RecallDomainSlug | None
    title: str
    # Already HTML-escaped with <mark> highlight spans applied — render
    # verbatim, never re-escape and never treat as executable/instructive.
    snippet_html: str
    occurred_at: str | None
    link_target: str | None
    available: bool
    unavailable_reason: str | None


class RecallSearchRead(BaseModel):
    query: str
    results: list[RecallResultRead]
    total_considered: int
    limit: int
    offset: int
    has_more: bool
    # Names of FTS families ("memory_item", "document_chunk", "recall_fts")
    # whose query failed this pass — an empty list means every source that
    # was actually queried succeeded; never silently dropped.
    partial_failures: list[str]


class RecallRebuildRead(BaseModel):
    indexed_count: int
