"""Phase 9 (corrected): normalized local caches for Google Calendar,
Google Health (Fitbit/Health data via the current Google Health API — the
legacy Fitbit Web API is being retired by Google in September 2026, see
docs/DECISIONS.md), and imported local documents, plus generic
per-provider connection state.

Nothing here ever stores a credential — OAuth tokens live only in the
macOS Keychain via app/credential_store.py. These tables hold only
normalized, typed, non-secret application data with source IDs,
timestamps, and lineage, per CLAUDE.md's data-ownership rules.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models import _new_uuid, _utcnow

INTEGRATION_PROVIDERS = ("google_calendar", "google_health")
CONNECTION_STATUSES = ("disconnected", "connected", "error")

DOCUMENT_STATUSES = ("processing", "ready", "error", "encrypted", "unsupported")


class IntegrationConnection(Base):
    """One row per external provider — never per-user (Jarvis is
    single-user). Never stores a token; only status/metadata."""

    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(f"provider IN {INTEGRATION_PROVIDERS}", name="ck_integration_connections_provider_valid"),
        CheckConstraint(f"status IN {CONNECTION_STATUSES}", name="ck_integration_connections_status_valid"),
    )

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="disconnected")
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    external_account_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CalendarCalendar(Base):
    """A calendar the user has chosen to let Jarvis access (selected=True)
    or that was merely seen while listing (selected=False)."""

    __tablename__ = "calendar_calendars"
    __table_args__ = (UniqueConstraint("external_calendar_id", name="uq_calendar_calendars_external_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    external_calendar_id: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    access_role: Mapped[str] = mapped_column(String(32), nullable=False, default="reader")
    is_owned: Mapped[bool] = mapped_column(nullable=False, default=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    events: Mapped[list["CalendarEventCache"]] = relationship(
        back_populates="calendar", cascade="all, delete-orphan"
    )


class CalendarEventCache(Base):
    """Normalized local cache of one Google Calendar event. Never
    authoritative — the real calendar is; this is a rebuildable read cache
    refreshed only by explicit manual sync."""

    __tablename__ = "calendar_event_cache"
    __table_args__ = (
        UniqueConstraint("calendar_id", "external_event_id", name="uq_calendar_event_cache_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    calendar_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_calendars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="(untitled)")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    all_day: Mapped[bool] = mapped_column(nullable=False, default=False)
    start_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_datetime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date_type | None] = mapped_column(Date, nullable=True)
    event_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    calendar: Mapped["CalendarCalendar"] = relationship(back_populates="events")


class GoogleHealthDailySummary(Base):
    """One row per calendar day of normalized Google Health data. Values
    are None when Google Health had nothing for that metric that day —
    never fabricated or estimated. `raw_json` retains the original API
    responses for lineage.

    `lightly_active_minutes`/`fairly_active_minutes`/`very_active_minutes`/
    `sedentary_minutes` predate the Phase 9 breadth correction (migration
    0007) and are kept, unpopulated, for schema/export compatibility with
    any archive created before that correction — never populated or read
    going forward; `active_zone_minutes` is the current equivalent."""

    __tablename__ = "google_health_daily_summaries"
    __table_args__ = (UniqueConstraint("date", name="uq_google_health_daily_summaries_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(nullable=True)
    floors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_zone_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_calories_kcal: Mapped[float | None] = mapped_column(nullable=True)
    calories_out: Mapped[float | None] = mapped_column(nullable=True)
    lightly_active_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fairly_active_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    very_active_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sedentary_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Google's own API types all three as `number` (float), not int64 —
    # `beatsPerMinuteAvg` in particular is routinely fractional (e.g.
    # 64.51...). A real 500 was found live when these were declared `int`
    # (docs/DECISIONS.md D66): the read schema rejected the genuine stored
    # float value.
    heart_rate_avg_bpm: Mapped[float | None] = mapped_column(nullable=True)
    heart_rate_min_bpm: Mapped[float | None] = mapped_column(nullable=True)
    heart_rate_max_bpm: Mapped[float | None] = mapped_column(nullable=True)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hrv_daily_rmssd_ms: Mapped[float | None] = mapped_column(nullable=True)
    oxygen_saturation_avg_percent: Mapped[float | None] = mapped_column(nullable=True)
    respiratory_rate_breaths_per_min: Mapped[float | None] = mapped_column(nullable=True)
    vo2_max: Mapped[float | None] = mapped_column(nullable=True)
    body_fat_percent: Mapped[float | None] = mapped_column(nullable=True)
    blood_glucose_mg_dl: Mapped[float | None] = mapped_column(nullable=True)
    sleep_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_minutes_asleep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_efficiency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    weight_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


GOOGLE_HEALTH_SESSION_TYPES = ("sleep", "exercise")


class GoogleHealthSession(Base):
    """One row per Google Health session (a sleep period or an exercise
    session) — event-shaped data, never collapsed into a single daily
    number. `external_id` is Google Health's own stable resource name
    (`users/.../dataTypes/{type}/dataPoints/{id}`), which makes repeated
    sync idempotent without Jarvis inventing its own identity scheme."""

    __tablename__ = "google_health_sessions"
    __table_args__ = (
        CheckConstraint(
            f"session_type IN {GOOGLE_HEALTH_SESSION_TYPES}", name="ck_google_health_sessions_type_valid"
        ),
        UniqueConstraint("session_type", "external_id", name="uq_google_health_sessions_external_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    session_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    activity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    calories_kcal: Mapped[float | None] = mapped_column(nullable=True)
    distance_km: Mapped[float | None] = mapped_column(nullable=True)
    average_heart_rate_bpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_asleep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    minutes_awake: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_device: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Document(Base):
    """A user-uploaded local document (explicit import only — never a
    scanned/watched folder). Original bytes live under the portable
    documents area; extracted text lives in DocumentChunk rows."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(f"status IN {DOCUMENT_STATUSES}", name="ck_documents_status_valid"),
        UniqueConstraint("sha256", name="uq_documents_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    domain_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="processing")
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="chunks")
