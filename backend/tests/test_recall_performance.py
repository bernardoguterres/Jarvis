"""Phase 12D: five-year-scale performance, using fictional bulk-generated
data — never Bernardo's real content. Proves search stays fast and
correctly bounded even with a large corpus, and that ranking/pagination
hold up at scale, not just on a handful of fixture rows."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import recall_service
from app.models import Domain

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)

# Five years of daily structured records (a bounded, realistic upper
# estimate for one person's LIFE-domain task/journal volume) plus a
# smaller volume of conversation messages — enough rows that an
# unindexed/linear-scan implementation would visibly slow down, while
# staying well within what an ordinary automated test should spend.
FIVE_YEAR_DAYS = 365 * 5


def _bulk_insert_recall_rows(db_session: Session, domain_slug: str, count: int, *, marker: str) -> None:
    domain_id = db_session.query(Domain).filter_by(slug=domain_slug).one().id
    rows = []
    for i in range(count):
        occurred = NOW - timedelta(days=i % FIVE_YEAR_DAYS)
        rows.append(
            {
                "source_type": "structured_record",
                "source_id": f"perf-{domain_slug}-{i}",
                "domain_slug": domain_slug,
                "occurred_at": occurred.isoformat(),
                "title": f"Task {i} {marker if i % 10 == 0 else ''}".strip(),
                "content": f"Routine daily note number {i} about ordinary life admin {marker if i % 10 == 0 else ''}".strip(),
            }
        )
    db_session.execute(
        text(
            "INSERT INTO recall_fts (source_type, source_id, domain_slug, occurred_at, title, content) "
            "VALUES (:source_type, :source_id, :domain_slug, :occurred_at, :title, :content)"
        ),
        rows,
    )
    db_session.commit()
    return domain_id


def test_search_stays_fast_and_correct_at_five_year_scale(db_session: Session) -> None:
    _bulk_insert_recall_rows(db_session, "life", 5000, marker="raretoken")
    _bulk_insert_recall_rows(db_session, "build", 3000, marker="raretoken")

    start = time.perf_counter()
    result = recall_service.search(db_session, "raretoken", limit=20)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"search took {elapsed:.3f}s at 8000-row scale, expected well under 2s"
    assert len(result.results) == 20
    assert result.total_considered >= 20
    assert all("raretoken" in r.snippet_html.lower() for r in result.results)


def test_pagination_remains_correct_at_scale(db_session: Session) -> None:
    _bulk_insert_recall_rows(db_session, "life", 2000, marker="pagetoken")

    seen_ids: set[str] = set()
    for offset in range(0, 100, 20):
        page = recall_service.search(db_session, "pagetoken", limit=20, offset=offset)
        page_ids = {r.source_id for r in page.results}
        assert page_ids.isdisjoint(seen_ids)
        seen_ids |= page_ids
    assert len(seen_ids) == 100


def test_source_availability_recheck_does_not_blow_up_at_scale(db_session: Session) -> None:
    """_resolve_availability re-queries the real source row per result —
    proving this stays a per-PAGE cost (bounded by `limit`), not a
    per-INDEXED-ROW cost, is what actually matters at scale."""
    _bulk_insert_recall_rows(db_session, "life", 5000, marker="availtoken")
    start = time.perf_counter()
    result = recall_service.search(db_session, "availtoken", limit=20)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0
    # Every one of these rows has no real structured_records row behind
    # it (they were inserted directly into recall_fts as bulk fixtures)
    # — truthfully reported as unavailable, not silently dropped.
    assert all(r.available is False for r in result.results)
