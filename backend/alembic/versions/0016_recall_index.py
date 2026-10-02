"""Recall: adds `recall_fts`, an FTS5 table for the sources that had no
full-text index yet (conversations, messages, structured records, domain
summaries, document names, Calendar events, action proposals, routine
runs, focus sessions). Memories and document chunks keep their existing
`memory_fts` and `document_fts` tables, and `recall_service.py` searches
all three together.

The table is derived data. This migration creates it empty; the startup
backfill in `app/main.py` fills it, and each write path keeps it in sync
through `sync_recall()`/`remove_recall()`.

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
    # some third way). Mirrors FocusSession/MissionFocusPin's own
    # source_type/source_id pointer pattern. domain_slug is a slug, not a
    # domain_id, deliberately: every source adapter resolves it once at
    # write time, so no query-time join against `domains` is ever needed
    # to filter by domain, and every result already speaks the same
    # vocabulary the frontend's domainOrder.ts does. NULL domain_slug
    # means "global/system" (an item with no single owning domain: a
    # general conversation, a routine run, a domain-less manual mission,
    # a global action proposal), always shown by default, since it
    # cannot be BODY/MIND/PEOPLE sensitive content by construction.
    # occurred_at is stored as an ISO-8601 UTC string (SQLite has no real
    # datetime type; sorting/comparing ISO-8601 strings lexically is
    # correct because they're zero-padded and always UTC) for the bounded
    # recency ranking signal. Never used to decide inclusion/exclusion,
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
