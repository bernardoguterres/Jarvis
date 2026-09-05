"""Phase 9 correction: extend Google Health beyond a narrow daily-summary
shape into a provider-independent metric ingestion layer (steps, distance,
floors, active zone minutes, calories, heart rate, resting HR, HRV, SpO2,
respiratory rate, VO2 max, weight, body fat, blood glucose as daily
summaries; sleep and exercise as full sessions). Forward-only — 0005 and
0006 are left untouched.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.add_column(sa.Column("floors", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_zone_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("active_calories_kcal", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("heart_rate_avg_bpm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("heart_rate_min_bpm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("heart_rate_max_bpm", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("oxygen_saturation_avg_percent", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("respiratory_rate_breaths_per_min", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("vo2_max", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("body_fat_percent", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("blood_glucose_mg_dl", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_platforms_json", sa.Text(), nullable=True))
        # calories_out was declared Integer in 0005 but the real API's
        # totalCalories.kcalSum is not necessarily a whole number — widen
        # to Float. Existing (always-NULL, per the bug fixed this session)
        # values are unaffected.
        batch_op.alter_column("calories_out", type_=sa.Float(), existing_type=sa.Integer())

    op.create_table(
        "google_health_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_type", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=300), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activity_type", sa.String(length=64), nullable=True),
        sa.Column("calories_kcal", sa.Float(), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("average_heart_rate_bpm", sa.Integer(), nullable=True),
        sa.Column("minutes_asleep", sa.Integer(), nullable=True),
        sa.Column("minutes_awake", sa.Integer(), nullable=True),
        sa.Column("stages_json", sa.Text(), nullable=True),
        sa.Column("source_platform", sa.String(length=32), nullable=True),
        sa.Column("source_device", sa.String(length=100), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("session_type IN ('sleep', 'exercise')", name="ck_google_health_sessions_type_valid"),
        sa.UniqueConstraint("session_type", "external_id", name="uq_google_health_sessions_external_id"),
    )
    op.create_index("ix_google_health_sessions_session_type", "google_health_sessions", ["session_type"])
    op.create_index("ix_google_health_sessions_end_time", "google_health_sessions", ["end_time"])


def downgrade() -> None:
    op.drop_index("ix_google_health_sessions_end_time", table_name="google_health_sessions")
    op.drop_index("ix_google_health_sessions_session_type", table_name="google_health_sessions")
    op.drop_table("google_health_sessions")

    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.alter_column("calories_out", type_=sa.Integer(), existing_type=sa.Float())
        batch_op.drop_column("source_platforms_json")
        batch_op.drop_column("blood_glucose_mg_dl")
        batch_op.drop_column("body_fat_percent")
        batch_op.drop_column("vo2_max")
        batch_op.drop_column("respiratory_rate_breaths_per_min")
        batch_op.drop_column("oxygen_saturation_avg_percent")
        batch_op.drop_column("heart_rate_max_bpm")
        batch_op.drop_column("heart_rate_min_bpm")
        batch_op.drop_column("heart_rate_avg_bpm")
        batch_op.drop_column("active_calories_kcal")
        batch_op.drop_column("active_zone_minutes")
        batch_op.drop_column("floors")
