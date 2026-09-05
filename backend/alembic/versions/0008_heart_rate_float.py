"""Fix a real bug found live (D66): heart_rate_avg_bpm/min/max were
declared Integer, but Google's own API types them as `number` (float) —
`beatsPerMinuteAvg` in particular is routinely fractional. A stored float
value caused a genuine unhandled 500 when read back through the
Integer-typed Pydantic schema. Forward-only — 0005-0007 are untouched.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.alter_column("heart_rate_avg_bpm", type_=sa.Float(), existing_type=sa.Integer())
        batch_op.alter_column("heart_rate_min_bpm", type_=sa.Float(), existing_type=sa.Integer())
        batch_op.alter_column("heart_rate_max_bpm", type_=sa.Float(), existing_type=sa.Integer())


def downgrade() -> None:
    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.alter_column("heart_rate_max_bpm", type_=sa.Integer(), existing_type=sa.Float())
        batch_op.alter_column("heart_rate_min_bpm", type_=sa.Integer(), existing_type=sa.Float())
        batch_op.alter_column("heart_rate_avg_bpm", type_=sa.Integer(), existing_type=sa.Float())
