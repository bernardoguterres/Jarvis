"""CRUD for validated structured records."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Domain
from app.models_memory import SENSITIVITY_LEVELS, StructuredRecord
from app.structured_records import RECORD_TYPE_DOMAIN_SLUG, StructuredRecordValidationError, validate_payload


class StructuredRecordError(Exception):
    pass


def create_structured_record(
    session: Session,
    *,
    domain_id: str,
    record_type: str,
    occurred_at: datetime,
    payload: dict,
    source_message_id: str | None = None,
    sensitivity: str = "normal",
) -> StructuredRecord:
    domain = session.get(Domain, domain_id)
    if domain is None:
        raise StructuredRecordError(f"Unknown domain_id: {domain_id!r}")

    expected_slug = RECORD_TYPE_DOMAIN_SLUG.get(record_type)
    if expected_slug is None:
        raise StructuredRecordError(f"Unknown record_type: {record_type!r}")
    if domain.slug != expected_slug:
        raise StructuredRecordError(
            f"record_type {record_type!r} belongs to domain {expected_slug!r}, not {domain.slug!r}."
        )

    if sensitivity not in SENSITIVITY_LEVELS:
        raise StructuredRecordError(f"sensitivity must be one of {SENSITIVITY_LEVELS}")

    try:
        validated = validate_payload(record_type, payload)
    except StructuredRecordValidationError as exc:
        raise StructuredRecordError(str(exc)) from exc

    record = StructuredRecord(
        domain_id=domain_id,
        record_type=record_type,
        occurred_at=occurred_at,
        payload_json=validated.model_dump_json(),
        source_message_id=source_message_id,
        sensitivity=sensitivity,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def list_structured_records(
    session: Session,
    *,
    domain_id: str | None = None,
    record_type: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[StructuredRecord]:
    limit = max(1, min(limit, 200))
    stmt = select(StructuredRecord)
    if domain_id is not None:
        stmt = stmt.where(StructuredRecord.domain_id == domain_id)
    if record_type is not None:
        stmt = stmt.where(StructuredRecord.record_type == record_type)
    if not include_archived:
        stmt = stmt.where(StructuredRecord.archived_at.is_(None))
    stmt = stmt.order_by(StructuredRecord.occurred_at.desc()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def archive_structured_record(session: Session, record_id: str) -> StructuredRecord:
    from datetime import timezone

    record = session.get(StructuredRecord, record_id)
    if record is None:
        raise StructuredRecordError(f"Unknown structured record: {record_id!r}")
    record.archived_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(record)
    return record


def payload_dict(record: StructuredRecord) -> dict:
    return json.loads(record.payload_json)
