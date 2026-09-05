from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app import structured_record_service
from app.models import Domain
from app.structured_record_service import StructuredRecordError, payload_dict

NOW = datetime.now(timezone.utc)


def _domain_id(session: Session, slug: str) -> str:
    return session.query(Domain).filter_by(slug=slug).one().id


@pytest.mark.parametrize(
    "slug,record_type,payload",
    [
        ("body", "body_weight", {"kilograms": 78.5}),
        ("body", "body_symptom", {"body_area": "knee", "description": "aching after runs"}),
        ("mind", "mind_checkin", {"mood": "calm", "note": "good day"}),
        ("people", "people_interaction", {"person": "Alex", "note": "caught up over coffee"}),
        ("path", "path_deadline", {"title": "UCL application", "due_date": "2026-10-01"}),
        ("build", "build_checkpoint", {"project": "Jarvis", "summary": "shipped Phase 4"}),
        ("life", "life_task", {"title": "Renew passport"}),
    ],
)
def test_every_initial_record_type_validates(
    db_session: Session, slug: str, record_type: str, payload: dict
) -> None:
    domain_id = _domain_id(db_session, slug)
    record = structured_record_service.create_structured_record(
        db_session, domain_id=domain_id, record_type=record_type, occurred_at=NOW, payload=payload
    )
    assert record.record_type == record_type
    assert payload_dict(record)["record_type"] == record_type


def test_invalid_domain_record_type_combination_rejected(db_session: Session) -> None:
    build_id = _domain_id(db_session, "build")
    with pytest.raises(StructuredRecordError):
        structured_record_service.create_structured_record(
            db_session,
            domain_id=build_id,
            record_type="body_weight",  # belongs to BODY, not BUILD
            occurred_at=NOW,
            payload={"kilograms": 80},
        )


def test_unknown_record_type_rejected(db_session: Session) -> None:
    body_id = _domain_id(db_session, "body")
    with pytest.raises(StructuredRecordError):
        structured_record_service.create_structured_record(
            db_session, domain_id=body_id, record_type="not_a_type", occurred_at=NOW, payload={}
        )


def test_missing_required_field_rejected(db_session: Session) -> None:
    body_id = _domain_id(db_session, "body")
    with pytest.raises(StructuredRecordError):
        structured_record_service.create_structured_record(
            db_session, domain_id=body_id, record_type="body_weight", occurred_at=NOW, payload={}
        )


def test_out_of_range_weight_rejected(db_session: Session) -> None:
    body_id = _domain_id(db_session, "body")
    with pytest.raises(StructuredRecordError):
        structured_record_service.create_structured_record(
            db_session,
            domain_id=body_id,
            record_type="body_weight",
            occurred_at=NOW,
            payload={"kilograms": -5},
        )


def test_unbounded_extra_fields_do_not_silently_pass_through(db_session: Session) -> None:
    body_id = _domain_id(db_session, "body")
    record = structured_record_service.create_structured_record(
        db_session,
        domain_id=body_id,
        record_type="body_weight",
        occurred_at=NOW,
        payload={"kilograms": 80, "unexpected_field": "should be dropped, not stored verbatim"},
    )
    stored = payload_dict(record)
    assert "unexpected_field" not in stored


def test_archive_excludes_from_default_listing(db_session: Session) -> None:
    body_id = _domain_id(db_session, "body")
    record = structured_record_service.create_structured_record(
        db_session, domain_id=body_id, record_type="body_weight", occurred_at=NOW, payload={"kilograms": 80}
    )
    structured_record_service.archive_structured_record(db_session, record.id)

    active = structured_record_service.list_structured_records(db_session, domain_id=body_id)
    assert record.id not in [r.id for r in active]

    with_archived = structured_record_service.list_structured_records(
        db_session, domain_id=body_id, include_archived=True
    )
    assert record.id in [r.id for r in with_archived]
