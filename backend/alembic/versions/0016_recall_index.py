"""Phase 12D: Unified Recall and Provenance — one deterministic, local
full-text search surface across all six domains, never a model feature.

Adds one new derived, rebuildable FTS5 virtual table, `recall_fts`, that
indexes the source types with no existing FTS index of their own:
conversations/messages, structured records, domain summaries, document
names (chunk *content* keeps using the existing `document_fts` table,
never duplicated here), cached Calendar events, action proposals,
routine run outputs, and Mission Control focus sessions. Memory items
keep using the existing `memory_fts` table unchanged — `recall_service.py`
queries `memory_fts`, `document_fts`, and this new `recall_fts` table
together and merges/ranks the results, rather than duplicating already-
indexed content into a second copy.

`recall_fts` is never authoritative — every row it contains is a rebuildable
derivative of a real row in another table, exactly like `memory_fts`
(migration 0003) and `document_fts` (migration 0005) before it. This
migration only creates the empty table; `app/recall_index_service.py`'s
`rebuild_recall_index()` backfills it for existing installations (run
automatically at backend startup if the table is found empty, mirroring
every other Phase 9-12 startup-sweep pattern in `app/main.py`), and every
relevant create/update/archive/delete write path calls the same module's
`sync_recall()`/`remove_recall()` to keep it live-synchronized afterward.

Forward-only — 0001-0015 are untouched.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # source_type/source_id: a typed pointer to the real row this recall
    # entry was derived from (never a copy that could itself go stale in
    # some third way) — mirrors FocusSession/MissionFocusPin's own
    # source_type/source_id pointer pattern. domain_slug is a slug, not a
    # domain_id, deliberately: every source adapter resolves it once at
    # write time, so no query-time join against `domains` is ever needed
    # to filter by domain, and every result already speaks the same
    # vocabulary the frontend's domainOrder.ts does. NULL domain_slug
    # means "global/system" (an item with no single owning domain — a
    # general conversation, a routine run, a domain-less manual mission,
    # a global action proposal) — always shown by default, since it
    # cannot be BODY/MIND/PEOPLE sensitive content by construction.
    # occurred_at is stored as an ISO-8601 UTC string (SQLite has no real
    # datetime type; sorting/comparing ISO-8601 strings lexically is
    # correct because they're zero-padded and always UTC) for the bounded
    # recency ranking signal — never used to decide inclusion/exclusion,
    # only to break ties among otherwise similarly-relevant results.
    op.execute(
        """
        CREATE VIRTUAL TABLE recall_fts USING fts5(
            source_type UNINDEXED,
            source_id UNINDEXED,
            domain_slug UNINDEXED,
            occurred_at UNINDEXED,
            title,
            content
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recall_fts")
