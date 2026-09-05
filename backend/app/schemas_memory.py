"""Pydantic request/response models for the Phase 4 memory/record/context API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_TITLE_LENGTH = 200
MAX_CONTENT_LENGTH = 4000


class MemoryVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_item_id: str
    version_number: int
    title: str
    kind: str
    content: str
    importance: int
    confidence: float
    sensitivity: str
    event_date: datetime | None
    change_reason: str | None
    source: str | None
    created_at: datetime


class MemoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope: str
    domain_id: str | None
    kind: str
    title: str
    status: str
    importance: int
    confidence: float
    sensitivity: str
    event_date: datetime | None
    created_at: datetime
    updated_at: datetime
    current_version_id: str | None
    supersedes_id: str | None
    superseded_by_id: str | None


class MemoryItemWithHistory(BaseModel):
    item: MemoryItemRead
    current_content: str | None
    versions: list[MemoryVersionRead]


class MemoryCreate(BaseModel):
    scope: str
    domain_id: str | None = None
    kind: str
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    sensitivity: str = "normal"
    event_date: datetime | None = None
    source_message_id: str | None = None
    source_conversation_id: str | None = None
    source_note: str | None = Field(default=None, max_length=300)
    change_reason: str | None = Field(default=None, max_length=300)


class MemoryEdit(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    kind: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sensitivity: str | None = None
    event_date: datetime | None = None
    change_reason: str | None = Field(default=None, max_length=300)


class MemorySupersede(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    kind: str | None = None
    importance: int | None = Field(default=None, ge=1, le=5)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    sensitivity: str | None = None
    event_date: datetime | None = None
    change_reason: str | None = Field(default=None, max_length=300)


class MemoryPermanentDelete(BaseModel):
    confirm_title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class DomainSummaryVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    domain_summary_id: str
    version_number: int
    content: str
    source: str | None
    created_at: datetime


class DomainSummaryRead(BaseModel):
    domain_id: str
    current_content: str | None
    current_version_id: str | None
    updated_at: datetime | None


class DomainSummarySet(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    source: str = Field(default="manual", max_length=64)


class StructuredRecordCreate(BaseModel):
    record_type: str
    occurred_at: datetime
    payload: dict
    source_message_id: str | None = None
    sensitivity: str = "normal"


class StructuredRecordRead(BaseModel):
    id: str
    domain_id: str
    record_type: str
    occurred_at: datetime
    payload: dict
    sensitivity: str
    created_at: datetime
    archived_at: datetime | None


class ContextSnapshotRead(BaseModel):
    id: str
    agent_run_id: str
    active_domain_id: str | None
    additional_domain_ids: list[str]
    global_memory_version_ids: list[str]
    domain_memory_version_ids: list[str]
    domain_summary_version_ids: list[str]
    structured_record_ids: list[str]
    recent_message_ids: list[str]
    retrieval_query: str
    retrieval_reasons: list[dict]
    estimated_context_chars: int
    document_chunk_ids: list[str] = []
    calendar_event_ids: list[str] = []
    google_health_summary_ids: list[str] = []
    created_at: datetime


class FtsRebuildResult(BaseModel):
    indexed_count: int
