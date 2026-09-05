from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import domain_summary_service, fts_service, memory_service, structured_record_service
from app.config import Settings, get_settings
from app.deps import get_db
from app.memory_service import MemoryNotFoundError, MemoryValidationError, PermanentDeletionError
from app.models import AgentRun, Domain
from app.models_memory import ContextSnapshot, MemoryItem
from app.recall_index_service import sync_recall
from app.schemas_memory import (
    ContextSnapshotRead,
    DomainSummaryRead,
    DomainSummarySet,
    DomainSummaryVersionRead,
    FtsRebuildResult,
    MemoryCreate,
    MemoryEdit,
    MemoryItemRead,
    MemoryItemWithHistory,
    MemoryPermanentDelete,
    MemorySupersede,
    MemoryVersionRead,
    StructuredRecordCreate,
    StructuredRecordRead,
)
from app.structured_record_service import StructuredRecordError, payload_dict

router = APIRouter(tags=["memory"])


def _get_domain_by_slug_or_404(db: Session, slug: str) -> Domain:
    domain = db.execute(select(Domain).where(Domain.slug == slug)).scalar_one_or_none()
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain


# --- Memories ---------------------------------------------------------------


@router.get("/api/memories", response_model=list[MemoryItemRead])
def list_memories(
    scope: str | None = None,
    domain_id: str | None = None,
    status: str | None = "active",
    kind: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MemoryItem]:
    return memory_service.list_memories(
        db, scope=scope, domain_id=domain_id, status=status, kind=kind, limit=limit, offset=offset
    )


@router.get("/api/memories/search", response_model=list[MemoryItemRead])
def search_memories(
    q: str,
    domain_id: str | None = None,
    include_global: bool = True,
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
) -> list[MemoryItem]:
    domain_ids = [domain_id] if domain_id else None
    hits = fts_service.search_memory_fts(
        db, q, domain_ids=domain_ids, include_global=include_global, limit=limit
    )
    items = []
    for memory_item_id, _score in hits:
        item = db.get(MemoryItem, memory_item_id)
        if item is not None:
            items.append(item)
    return items


@router.post("/api/memories", response_model=MemoryItemRead, status_code=201)
def create_memory(payload: MemoryCreate, db: Session = Depends(get_db)) -> MemoryItem:
    try:
        return memory_service.create_memory(
            db,
            scope=payload.scope,
            domain_id=payload.domain_id,
            kind=payload.kind,
            title=payload.title,
            content=payload.content,
            importance=payload.importance,
            confidence=payload.confidence,
            sensitivity=payload.sensitivity,
            event_date=payload.event_date,
            source_message_id=payload.source_message_id,
            source_conversation_id=payload.source_conversation_id,
            source_note=payload.source_note,
            change_reason=payload.change_reason,
        )
    except MemoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/memories/{memory_id}", response_model=MemoryItemWithHistory)
def get_memory(memory_id: str, db: Session = Depends(get_db)) -> MemoryItemWithHistory:
    try:
        item = memory_service.get_memory_or_404(db, memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")

    versions = list(item.versions)
    return MemoryItemWithHistory(
        item=MemoryItemRead.model_validate(item),
        current_content=item.current_version.content if item.current_version else None,
        versions=[MemoryVersionRead.model_validate(v) for v in versions],
    )


@router.post("/api/memories/{memory_id}/edit", response_model=MemoryItemRead)
def edit_memory(memory_id: str, payload: MemoryEdit, db: Session = Depends(get_db)) -> MemoryItem:
    try:
        return memory_service.edit_memory(
            db,
            memory_id,
            title=payload.title,
            content=payload.content,
            kind=payload.kind,
            importance=payload.importance,
            confidence=payload.confidence,
            sensitivity=payload.sensitivity,
            event_date=payload.event_date,
            change_reason=payload.change_reason,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")
    except MemoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/api/memories/{memory_id}/supersede", response_model=MemoryItemRead)
def supersede_memory(
    memory_id: str, payload: MemorySupersede, db: Session = Depends(get_db)
) -> MemoryItem:
    try:
        return memory_service.supersede_memory(
            db,
            memory_id,
            title=payload.title,
            content=payload.content,
            kind=payload.kind,
            importance=payload.importance,
            confidence=payload.confidence,
            sensitivity=payload.sensitivity,
            event_date=payload.event_date,
            change_reason=payload.change_reason,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")
    except MemoryValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/api/memories/{memory_id}/archive", response_model=MemoryItemRead)
def archive_memory(memory_id: str, db: Session = Depends(get_db)) -> MemoryItem:
    try:
        return memory_service.archive_memory(db, memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/api/memories/{memory_id}/unarchive", response_model=MemoryItemRead)
def unarchive_memory(memory_id: str, db: Session = Depends(get_db)) -> MemoryItem:
    try:
        return memory_service.unarchive_memory(db, memory_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/api/memories/{memory_id}/delete", status_code=204, response_model=None)
def permanently_delete_memory(
    memory_id: str,
    payload: MemoryPermanentDelete,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    try:
        memory_service.permanently_delete_memory(
            db, settings, memory_id, typed_confirmation=payload.confirm_title
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found")
    except PermanentDeletionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# --- Domain summaries --------------------------------------------------------


@router.get("/api/domains/{slug}/summary", response_model=DomainSummaryRead)
def get_domain_summary(slug: str, db: Session = Depends(get_db)) -> DomainSummaryRead:
    domain = _get_domain_by_slug_or_404(db, slug)
    summary = domain_summary_service.get_or_create_summary_slot(db, domain.id)
    db.commit()
    return DomainSummaryRead(
        domain_id=domain.id,
        current_content=summary.current_version.content if summary.current_version else None,
        current_version_id=summary.current_version_id,
        updated_at=summary.updated_at,
    )


@router.put("/api/domains/{slug}/summary", response_model=DomainSummaryRead)
def set_domain_summary(
    slug: str, payload: DomainSummarySet, db: Session = Depends(get_db)
) -> DomainSummaryRead:
    domain = _get_domain_by_slug_or_404(db, slug)
    summary = domain_summary_service.set_domain_summary(
        db, domain.id, payload.content, source=payload.source
    )
    sync_recall(db, "domain_summary", domain.id)
    db.commit()
    return DomainSummaryRead(
        domain_id=domain.id,
        current_content=summary.current_version.content if summary.current_version else None,
        current_version_id=summary.current_version_id,
        updated_at=summary.updated_at,
    )


@router.delete("/api/domains/{slug}/summary", response_model=DomainSummaryRead)
def clear_domain_summary(slug: str, db: Session = Depends(get_db)) -> DomainSummaryRead:
    domain = _get_domain_by_slug_or_404(db, slug)
    summary = domain_summary_service.clear_domain_summary(db, domain.id)
    sync_recall(db, "domain_summary", domain.id)
    db.commit()
    return DomainSummaryRead(
        domain_id=domain.id, current_content=None, current_version_id=None, updated_at=summary.updated_at
    )


@router.get("/api/domains/{slug}/summary/history", response_model=list[DomainSummaryVersionRead])
def get_domain_summary_history(slug: str, db: Session = Depends(get_db)) -> list:
    domain = _get_domain_by_slug_or_404(db, slug)
    return domain_summary_service.get_summary_history(db, domain.id)


# --- Structured records -------------------------------------------------------


@router.post("/api/domains/{slug}/records", response_model=StructuredRecordRead, status_code=201)
def create_structured_record(
    slug: str, payload: StructuredRecordCreate, db: Session = Depends(get_db)
) -> StructuredRecordRead:
    domain = _get_domain_by_slug_or_404(db, slug)
    try:
        record = structured_record_service.create_structured_record(
            db,
            domain_id=domain.id,
            record_type=payload.record_type,
            occurred_at=payload.occurred_at,
            payload=payload.payload,
            source_message_id=payload.source_message_id,
            sensitivity=payload.sensitivity,
        )
    except StructuredRecordError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sync_recall(db, "structured_record", record.id)
    db.commit()
    return StructuredRecordRead(
        id=record.id,
        domain_id=record.domain_id,
        record_type=record.record_type,
        occurred_at=record.occurred_at,
        payload=payload_dict(record),
        sensitivity=record.sensitivity,
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


@router.get("/api/domains/{slug}/records", response_model=list[StructuredRecordRead])
def list_structured_records(
    slug: str,
    record_type: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[StructuredRecordRead]:
    domain = _get_domain_by_slug_or_404(db, slug)
    records = structured_record_service.list_structured_records(
        db,
        domain_id=domain.id,
        record_type=record_type,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    return [
        StructuredRecordRead(
            id=r.id,
            domain_id=r.domain_id,
            record_type=r.record_type,
            occurred_at=r.occurred_at,
            payload=payload_dict(r),
            sensitivity=r.sensitivity,
            created_at=r.created_at,
            archived_at=r.archived_at,
        )
        for r in records
    ]


@router.post("/api/records/{record_id}/archive", response_model=StructuredRecordRead)
def archive_structured_record(record_id: str, db: Session = Depends(get_db)) -> StructuredRecordRead:
    try:
        record = structured_record_service.archive_structured_record(db, record_id)
    except StructuredRecordError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    sync_recall(db, "structured_record", record.id)
    db.commit()
    return StructuredRecordRead(
        id=record.id,
        domain_id=record.domain_id,
        record_type=record.record_type,
        occurred_at=record.occurred_at,
        payload=payload_dict(record),
        sensitivity=record.sensitivity,
        created_at=record.created_at,
        archived_at=record.archived_at,
    )


# --- Context snapshots ---------------------------------------------------------


@router.get("/api/agent-runs/{run_id}/context", response_model=ContextSnapshotRead)
def get_context_snapshot(run_id: str, db: Session = Depends(get_db)) -> ContextSnapshotRead:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    snapshot = db.execute(
        select(ContextSnapshot).where(ContextSnapshot.agent_run_id == run_id)
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No context snapshot for this run")

    return ContextSnapshotRead(
        id=snapshot.id,
        agent_run_id=snapshot.agent_run_id,
        active_domain_id=snapshot.active_domain_id,
        additional_domain_ids=json.loads(snapshot.additional_domain_ids_json),
        global_memory_version_ids=json.loads(snapshot.global_memory_version_ids_json),
        domain_memory_version_ids=json.loads(snapshot.domain_memory_version_ids_json),
        domain_summary_version_ids=json.loads(snapshot.domain_summary_version_ids_json),
        structured_record_ids=json.loads(snapshot.structured_record_ids_json),
        recent_message_ids=json.loads(snapshot.recent_message_ids_json),
        retrieval_query=snapshot.retrieval_query,
        retrieval_reasons=json.loads(snapshot.retrieval_reasons_json),
        estimated_context_chars=snapshot.estimated_context_chars,
        document_chunk_ids=json.loads(snapshot.document_chunk_ids_json),
        calendar_event_ids=json.loads(snapshot.calendar_event_ids_json),
        google_health_summary_ids=json.loads(snapshot.google_health_summary_ids_json),
        created_at=snapshot.created_at,
    )


# --- FTS index maintenance -----------------------------------------------------


@router.post("/api/memory-index/rebuild", response_model=FtsRebuildResult)
def rebuild_memory_index(db: Session = Depends(get_db)) -> FtsRebuildResult:
    count = fts_service.rebuild_fts(db)
    return FtsRebuildResult(indexed_count=count)


@router.get("/api/memory-index/status", response_model=FtsRebuildResult)
def memory_index_status(db: Session = Depends(get_db)) -> FtsRebuildResult:
    count = db.execute(text("SELECT COUNT(*) FROM memory_fts")).scalar_one()
    return FtsRebuildResult(indexed_count=count)
