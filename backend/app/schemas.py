"""Pydantic request/response models for the Phase 1 API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_MESSAGE_LENGTH = 8000


class DomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    domain_id: str | None
    title: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class MessageCreate(BaseModel):
    role: str = Field(default="user")
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    model_used: str | None


class HealthRead(BaseModel):
    status: str


class DataDirRead(BaseModel):
    path: str


class ExportRead(BaseModel):
    filename: str
    created_at_utc: str
    size_bytes: int
    included_components: list[str]


class ExportListItem(BaseModel):
    filename: str
    size_bytes: int
    created_at_utc: str | None = None


class BackupRead(BaseModel):
    category: str
    filename: str
    created_at_utc: str
    size_bytes: int
    sha256: str


class LatestBackupInfo(BaseModel):
    latest: dict | None
    by_category: dict[str, dict | None]


class ImportValidationRead(BaseModel):
    ok: bool
    errors: list[str]
    manifest: dict | None = None


class RestoreRead(BaseModel):
    domains_restored: int
    conversations_restored: int
    messages_restored: int
    documents_restored: int
    domain_summaries_restored: int
    skills_restored: int
    schema_revision_before: str | None
    schema_revision_after: str
    rollback_dir: str | None
    target_dir: str
    hermes_profile_export_path: str | None = None
    hermes_profile_import_command: str | None = None


MAX_TURN_CONTENT_LENGTH = 4000


MAX_ADDITIONAL_DOMAINS = 3


class TurnCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_TURN_CONTENT_LENGTH)
    idempotency_key: str = Field(min_length=1, max_length=128)
    additional_domain_ids: list[str] = Field(default_factory=list, max_length=MAX_ADDITIONAL_DOMAINS)


class UsageRead(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class TurnErrorRead(BaseModel):
    code: str
    summary: str


class TurnRead(BaseModel):
    run_id: str
    status: str
    user_message: MessageRead
    assistant_message: MessageRead | None
    provider: str
    model: str
    latency_ms: int | None
    usage: UsageRead | None
    context_snapshot_id: str | None = None
    error: TurnErrorRead | None


class AgentStatusRead(BaseModel):
    hermes_available: bool
    model_configured: bool
    model: str | None
    provider: str
