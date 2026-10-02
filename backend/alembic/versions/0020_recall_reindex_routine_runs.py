"""Empties `recall_fts` so routine runs are re-indexed without their
BODY/MIND/PEOPLE sections, which the old renderer included and which
were therefore searchable from Recall, Research and Decisions.

The index is derived data. The startup backfill in `app/main.py` rebuilds
an empty index with the current renderers. Routine outputs are not
touched, and restoring an older archive runs this same migration.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-02

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM recall_fts")


def downgrade() -> None:
    # Nothing to restore: the index is derived data, and the startup
    # backfill repopulates it on the next launch either way.
    pass
