"""Privacy fix: routine runs are indexed in `recall_fts` as global, and
before this revision their indexed text included BODY/MIND/PEOPLE sections
whenever Bernardo had opted those domains into a routine. That made the
text searchable from default Recall and from Research/Decision evidence
search. `app/recall_index_service.py` now indexes only LIFE/PATH/BUILD
sections, but rows written by the old renderer would stay searchable.

`recall_fts` is derived and never authoritative, so this migration empties
it. The existing startup backfill in `app/main.py` (which runs
`rebuild_recall_index()` whenever the table is empty) then re-renders every
row with the current renderers. Routine outputs themselves
(`routine_runs.output_json`) are untouched and stay fully visible in the
Routine Centre. A restore of an older archive passes through this same
migration, so it cannot bring the old rows back either.

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
