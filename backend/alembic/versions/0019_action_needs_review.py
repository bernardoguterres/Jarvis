"""Adds a `needs_review` status to action_proposals, so a Calendar write
interrupted by a crash is never reported as failed when its real outcome
is unknown. Startup recovery can now tell succeeded, safe to retry, and
uncertain apart.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-11

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = (
    "status IN ('proposed', 'approved', 'denied', 'expired', 'executing', 'succeeded', 'failed')"
)
_NEW = (
    "status IN ('proposed', 'approved', 'denied', 'expired', 'executing', 'succeeded', 'failed', "
    "'needs_review')"
)


def upgrade() -> None:
    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.drop_constraint("ck_action_proposals_status_valid", type_="check")
        batch_op.create_check_constraint("ck_action_proposals_status_valid", _NEW)


def downgrade() -> None:
    # Any row already recorded as needs_review is reverted to failed rather
    # than left violating the restored (narrower) constraint. This mirrors
    # the honest-but-conservative choice startup recovery made before this
    # migration existed.
    op.execute("UPDATE action_proposals SET status = 'failed' WHERE status = 'needs_review'")
    with op.batch_alter_table("action_proposals") as batch_op:
        batch_op.drop_constraint("ck_action_proposals_status_valid", type_="check")
        batch_op.create_check_constraint("ck_action_proposals_status_valid", _OLD)
