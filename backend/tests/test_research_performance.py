"""Phase 12E: a realistically large evidence set (hundreds of items) and
many brief versions on one workspace, using fictional bulk-generated
content — never Bernardo's real data. Proves the deterministic outline,
evidence listing, and citation-availability recheck all stay fast and
correct at a scale well beyond ordinary interactive use."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import research_service as rs
from app.models import Conversation, Domain, Message
from app.recall_index_service import sync_recall

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)

EVIDENCE_COUNT = 300
CLASSIFICATIONS = ("supporting", "contradicting", "contextual", "unresolved")


def _bulk_add_evidence(db_session: Session, workspace_id: str, count: int) -> list[str]:
    build_id = db_session.query(Domain).filter_by(slug="build").one().id
    evidence_ids: list[str] = []
    for i in range(count):
        conv = Conversation(domain_id=build_id, title=f"Research thread {i}")
        db_session.add(conv)
        db_session.flush()
        msg = Message(conversation_id=conv.id, role="user", content=f"Finding number {i} about tokenizer behavior.")
        db_session.add(msg)
        db_session.flush()
        sync_recall(db_session, "conversation", conv.id)
        sync_recall(db_session, "message", msg.id)
        evidence = rs.add_evidence(
            db_session, workspace_id, source_type="message", source_id=msg.id,
            classification=CLASSIFICATIONS[i % len(CLASSIFICATIONS)],
        )
        evidence_ids.append(evidence.id)
    return evidence_ids


def test_deterministic_brief_stays_fast_and_correct_at_scale(db_session: Session) -> None:
    ws = rs.create_workspace(db_session, title="Large tokenizer research workspace")
    start = time.perf_counter()
    evidence_ids = _bulk_add_evidence(db_session, ws.id, EVIDENCE_COUNT)
    add_elapsed = time.perf_counter() - start
    assert add_elapsed < 30.0, f"adding {EVIDENCE_COUNT} evidence rows took {add_elapsed:.2f}s"

    start = time.perf_counter()
    version = rs.generate_deterministic_brief(db_session, ws.id)
    gen_elapsed = time.perf_counter() - start
    assert gen_elapsed < 5.0, f"deterministic brief generation took {gen_elapsed:.2f}s at {EVIDENCE_COUNT}-evidence scale"

    import json

    citations = json.loads(version.citations_json)
    assert len(citations) == EVIDENCE_COUNT
    assert {c["evidence_id"] for c in citations} == set(evidence_ids)
    # Citation numbers are a contiguous 1..N sequence, no gaps or dupes.
    assert sorted(c["number"] for c in citations) == list(range(1, EVIDENCE_COUNT + 1))


def test_many_brief_versions_all_remain_independently_readable(db_session: Session) -> None:
    ws = rs.create_workspace(db_session, title="Versioning stress test")
    _bulk_add_evidence(db_session, ws.id, 20)

    version_ids = []
    for _ in range(15):
        version = rs.generate_deterministic_brief(db_session, ws.id)
        version_ids.append(version.id)

    versions = rs.list_brief_versions(db_session, ws.id)
    assert len(versions) == 15
    assert [v.version_number for v in versions] == list(range(15, 0, -1))  # newest first

    # Every historical version is still independently fetchable and intact.
    for version_id in version_ids:
        version = rs.get_brief_version(db_session, ws.id, version_id)
        assert version.sections_json


def test_evidence_listing_and_availability_recheck_bounded_by_page_not_index_size(db_session: Session) -> None:
    ws = rs.create_workspace(db_session, title="Availability scale test")
    _bulk_add_evidence(db_session, ws.id, EVIDENCE_COUNT)

    start = time.perf_counter()
    evidence = rs.list_evidence(db_session, ws.id)
    fields = [rs.evidence_read_fields(db_session, e) for e in evidence[:20]]
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0
    assert len(evidence) == EVIDENCE_COUNT
    assert all(f["available"] for f in fields)
