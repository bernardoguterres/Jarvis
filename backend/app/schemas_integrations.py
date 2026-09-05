"""Pydantic request/response models for the Phase 9 integrations/documents
API. Never includes a token/credential field anywhere."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class IntegrationConnectionRead(BaseModel):
    provider: str
    status: str
    scopes: list[str]
    external_account_label: str | None
    connected_at: datetime | None
    last_sync_at: datetime | None
    last_sync_status: str | None
    last_error: str | None


class OAuthStartRequest(BaseModel):
    include_write_scope: bool = False


class OAuthStartResponse(BaseModel):
    authorization_url: str


class CalendarCalendarRead(BaseModel):
    id: str
    external_calendar_id: str
    summary: str
    access_role: str
    is_owned: bool
    timezone: str | None
    selected: bool


class CalendarSelectRequest(BaseModel):
    selected: bool


class CalendarEventRead(BaseModel):
    id: str
    calendar_id: str
    external_event_id: str
    title: str
    description: str | None
    location: str | None
    all_day: bool
    start_datetime: datetime | None
    end_datetime: datetime | None
    start_date: date | None
    end_date: date | None
    event_timezone: str | None
    fetched_at: datetime


class GoogleHealthDailySummaryRead(BaseModel):
    date: date
    steps: int | None
    distance_km: float | None
    floors: int | None
    active_zone_minutes: int | None
    active_calories_kcal: float | None
    calories_out: float | None
    heart_rate_avg_bpm: float | None
    heart_rate_min_bpm: float | None
    heart_rate_max_bpm: float | None
    resting_heart_rate: int | None
    hrv_daily_rmssd_ms: float | None
    oxygen_saturation_avg_percent: float | None
    respiratory_rate_breaths_per_min: float | None
    vo2_max: float | None
    body_fat_percent: float | None
    blood_glucose_mg_dl: float | None
    sleep_duration_ms: int | None
    sleep_minutes_asleep: int | None
    sleep_efficiency: int | None
    sleep_type: str | None
    weight_kg: float | None
    weight_source: str | None
    fetched_at: datetime


class GoogleHealthSessionRead(BaseModel):
    session_type: str
    start_time: datetime
    end_time: datetime
    activity_type: str | None
    calories_kcal: float | None
    distance_km: float | None
    average_heart_rate_bpm: int | None
    minutes_asleep: int | None
    minutes_awake: int | None
    source_platform: str | None
    source_device: str | None
    fetched_at: datetime


class GoogleHealthMetricGroupStatus(BaseModel):
    category: str
    has_data: bool
    last_error: str | None = None


class GoogleHealthSyncRequest(BaseModel):
    days_back: int = 7


class DocumentRead(BaseModel):
    id: str
    domain_id: str
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    page_count: int | None
    status: str
    error_detail: str | None
    chunk_count: int
    created_at: datetime


class DocumentChunkRead(BaseModel):
    id: str
    chunk_index: int
    page_number: int | None
    content: str


class DocumentWithChunks(BaseModel):
    document: DocumentRead
    chunks: list[DocumentChunkRead]


class DocumentDeleteRequest(BaseModel):
    confirm_filename: str
