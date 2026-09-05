"""Phase 12F: a realistically large decision (many options, criteria,
evidence items) and many brief versions, using fictional bulk-generated
content — never Bernardo's real data. Proves the deterministic score
breakdown, evidence listing, and brief generation all stay fast and
correct at a scale well beyond ordinary interactive use."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import decision_service as ds
from app.models import Conversation, Domain, Message
from app.recall_index_service import sync_recall

NOW = datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc)

OPTION_COUNT = 15
CRITERION_COUNT = 15
EVIDENCE_COUNT = 150


def _bulk_evidence(db_session: Session, decision_id: str, count: int) -> list[str]:
    build_id = db_session.query(Domain).filter_by(slug="build").one().id
    ids = []
    for i in range(count):
        conv = Conversation(domain_id=build_id, title=f"Thread {i}")
        db_session.add(conv)
        db_session.flush()
        msg = Message(conversation_id=conv.id, role="user", content=f"Finding {i} about tokenizer behavior.")
        db_session.add(msg)
        db_session.flush()
        sync_recall(db_session, "conversation", conv.id)
        sync_recall(db_session, "message", msg.id)
        evidence = ds.add_evidence(
            db_session, decision_id, source_type="message", source_id=msg.id,
            stance=("supporting", "contradicting", "contextual", "unresolved")[i % 4],
        )
        ids.append(evidence.id)
    return ids


def test_score_breakdown_and_brief_stay_fast_and_correct_at_scale(db_session: Session) -> None:
    decision = ds.create_decision(db_session, title="Large-scale tokenizer decision")

    start = time.perf_counter()
    options = [ds.add_option(db_session, decision.id, name=f"Option {i}") for i in range(OPTION_COUNT)]
    criteria = [ds.add_criterion(db_session, decision.id, name=f"Criterion {i}", weight=(i % 5) + 1) for i in range(CRITERION_COUNT)]
    for oi, option in enumerate(options):
        for ci, criterion in enumerate(criteria):
            if (oi + ci) % 3 != 0:  # deliberately leave some unassessed
                ds.set_assessment(db_session, decision.id, option_id=option.id, criterion_id=criterion.id, score=((oi + ci) % 5) + 1)
    setup_elapsed = time.perf_counter() - start
    assert setup_elapsed < 15.0, f"setting up {OPTION_COUNT}x{CRITERION_COUNT} assessments took {setup_elapsed:.2f}s"

    start = time.perf_counter()
    evidence_ids = _bulk_evidence(db_session, decision.id, EVIDENCE_COUNT)
    evidence_elapsed = time.perf_counter() - start
    assert evidence_elapsed < 30.0, f"adding {EVIDENCE_COUNT} evidence rows took {evidence_elapsed:.2f}s"

    start = time.perf_counter()
    breakdown = ds.compute_score_breakdown(
        ds.list_options(db_session, decision.id), ds.list_criteria(db_session, decision.id), ds.list_assessments(db_session, decision.id)
    )
    score_elapsed = time.perf_counter() - start
    assert score_elapsed < 1.0, f"score breakdown over {OPTION_COUNT}x{CRITERION_COUNT} took {score_elapsed:.3f}s"
    assert len(breakdown.options) == OPTION_COUNT
    assert breakdown.incomplete is True

    start = time.perf_counter()
    version = ds.generate_deterministic_brief(db_session, decision.id)
    brief_elapsed = time.perf_counter() - start
    assert brief_elapsed < 5.0, f"deterministic brief generation took {brief_elapsed:.2f}s at this scale"

    citations = json.loads(version.citations_json)
    assert len(citations) == EVIDENCE_COUNT
    assert {c["evidence_id"] for c in citations} == set(evidence_ids)
    assert sorted(c["number"] for c in citations) == list(range(1, EVIDENCE_COUNT + 1))


def test_many_brief_versions_all_remain_independently_readable(db_session: Session) -> None:
    decision = ds.create_decision(db_session, title="Versioning stress test")
    ds.add_option(db_session, decision.id, name="opt")

    version_ids = []
    for _ in range(15):
        version = ds.generate_deterministic_brief(db_session, decision.id)
        version_ids.append(version.id)

    versions = ds.list_brief_versions(db_session, decision.id)
    assert len(versions) == 15
    assert [v.version_number for v in versions] == list(range(15, 0, -1))

    for version_id in version_ids:
        version = ds.get_brief_version(db_session, decision.id, version_id)
        assert version.sections_json
