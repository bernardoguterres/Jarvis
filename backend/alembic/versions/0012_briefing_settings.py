"""Phase 12A: current situational briefing — persisted privacy settings
for the on-demand Home briefing. Forward-only — 0001-0011 are untouched.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-29

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "briefing_settings",
        sa.Column("id", sa.String(length=16), primary_key=True),
        sa.Column("include_body", sa.Boolean(), nullable=False),
        sa.Column("include_mind", sa.Boolean(), nullable=False),
        sa.Column("include_people", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Bernardo's already-recorded privacy selection (CLAUDE.md,
    # docs/ROADMAP.md Phase 10B): BODY included, MIND and PEOPLE excluded.
    op.execute(
        "INSERT INTO briefing_settings "
        "(id, include_body, include_mind, include_people, created_at, updated_at) VALUES "
        "('singleton', 1, 0, 0, datetime('now'), datetime('now'))"
    )


def downgrade() -> None:
    op.drop_table("briefing_settings")
