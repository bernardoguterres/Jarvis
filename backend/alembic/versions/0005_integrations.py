"""Phase 9: integration connections, Google Calendar cache, Fitbit daily
summaries, and imported local documents.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("external_account_label", sa.String(length=200), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=16), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('google_calendar', 'fitbit')", name="ck_integration_connections_provider_valid"
        ),
        sa.CheckConstraint(
            "status IN ('disconnected', 'connected', 'error')", name="ck_integration_connections_status_valid"
        ),
    )

    op.create_table(
        "calendar_calendars",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_calendar_id", sa.String(length=300), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("access_role", sa.String(length=32), nullable=False),
        sa.Column("is_owned", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("external_calendar_id", name="uq_calendar_calendars_external_id"),
    )
    op.create_index("ix_calendar_calendars_external_calendar_id", "calendar_calendars", ["external_calendar_id"])

    op.create_table(
        "calendar_event_cache",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "calendar_id",
            sa.String(length=36),
            sa.ForeignKey("calendar_calendars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_event_id", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("event_timezone", sa.String(length=64), nullable=True),
        sa.Column("etag", sa.String(length=200), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("calendar_id", "external_event_id", name="uq_calendar_event_cache_external_id"),
    )
    op.create_index("ix_calendar_event_cache_calendar_id", "calendar_event_cache", ["calendar_id"])

    op.create_table(
        "fitbit_daily_summaries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("calories_out", sa.Integer(), nullable=True),
        sa.Column("lightly_active_minutes", sa.Integer(), nullable=True),
        sa.Column("fairly_active_minutes", sa.Integer(), nullable=True),
        sa.Column("very_active_minutes", sa.Integer(), nullable=True),
        sa.Column("sedentary_minutes", sa.Integer(), nullable=True),
        sa.Column("resting_heart_rate", sa.Integer(), nullable=True),
        sa.Column("hrv_daily_rmssd_ms", sa.Float(), nullable=True),
        sa.Column("sleep_duration_ms", sa.Integer(), nullable=True),
        sa.Column("sleep_minutes_asleep", sa.Integer(), nullable=True),
        sa.Column("sleep_efficiency", sa.Integer(), nullable=True),
        sa.Column("sleep_type", sa.String(length=16), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("weight_source", sa.String(length=32), nullable=True),
        sa.Column("raw_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("date", name="uq_fitbit_daily_summaries_date"),
    )
    op.create_index("ix_fitbit_daily_summaries_date", "fitbit_daily_summaries", ["date"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "domain_id", sa.String(length=36), sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("original_filename", sa.String(length=300), nullable=False),
        sa.Column("stored_relative_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'error', 'encrypted', 'unsupported')",
            name="ck_documents_status_valid",
        ),
        sa.UniqueConstraint("sha256", name="uq_documents_sha256"),
    )
    op.create_index("ix_documents_domain_id", "documents", ["domain_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "document_id", sa.String(length=36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_doc_index"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    # Derived, rebuildable FTS5 index over document chunk text. Never
    # authoritative — document_chunks is the source of truth (same pattern
    # as memory_fts in 0003).
    op.execute(
        """
        CREATE VIRTUAL TABLE document_fts USING fts5(
            document_id UNINDEXED,
            chunk_id UNINDEXED,
            domain_id UNINDEXED,
            content
        )
        """
    )

    # Context snapshots (Phase 4) now also record exactly which document
    # chunks / calendar events / Fitbit daily summaries were used, so
    # integration data is auditable the same way memory/records already are.
    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.add_column(sa.Column("document_chunk_ids_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("calendar_event_ids_json", sa.Text(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("fitbit_summary_ids_json", sa.Text(), nullable=False, server_default="[]"))

    # Extend the Phase 8 action_proposals capability CHECK constraint to
    # allow the three new Google Calendar write capabilities.
    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.drop_constraint("ck_action_proposals_capability_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_action_proposals_capability_valid",
            "capability_id IN ('memory.create', 'structured_record.create', 'domain_summary.update', "
            "'google_calendar.event.create', 'google_calendar.event.update', 'google_calendar.event.delete')",
        )


def downgrade() -> None:
    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.drop_column("fitbit_summary_ids_json")
        batch_op.drop_column("calendar_event_ids_json")
        batch_op.drop_column("document_chunk_ids_json")

    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.drop_constraint("ck_action_proposals_capability_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_action_proposals_capability_valid",
            "capability_id IN ('memory.create', 'structured_record.create', 'domain_summary.update')",
        )

    op.execute("DROP TABLE IF EXISTS document_fts")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_domain_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_fitbit_daily_summaries_date", table_name="fitbit_daily_summaries")
    op.drop_table("fitbit_daily_summaries")
    op.drop_index("ix_calendar_event_cache_calendar_id", table_name="calendar_event_cache")
    op.drop_table("calendar_event_cache")
    op.drop_index("ix_calendar_calendars_external_calendar_id", table_name="calendar_calendars")
    op.drop_table("calendar_calendars")
    op.drop_table("integration_connections")
