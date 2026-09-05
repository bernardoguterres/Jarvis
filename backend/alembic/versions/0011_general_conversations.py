"""Phase 6: general Jarvis conversation scope. This is NOT a seventh
domain — the `domains` table is untouched and still seeds exactly six rows
(BODY, MIND, PEOPLE, PATH, BUILD, LIFE). A conversation's `domain_id`
becomes nullable; NULL means "general conversation" (no fixed domain
context). `context_snapshots.active_domain_id` becomes nullable to match,
so a general turn's audit snapshot can truthfully record "no active
domain" instead of being forced to name one that was never used.

Forward-only — 0001-0010 are untouched.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-28

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite has no ALTER COLUMN — batch mode recreates the table (create
    # new, copy rows, drop old, rename). `app/database.py` forces
    # `PRAGMA foreign_keys=ON` on every connection Alembic included, so
    # without disabling it here, dropping the old `conversations` table
    # mid-recreation would CASCADE DELETE every `messages` and `agent_runs`
    # row referencing it (and, transitively, every `context_snapshots` row
    # referencing those). This was caught live by the existing
    # test_migration_0002/0003 data-preservation tests before ever
    # reaching real data — never remove this toggle from a batch operation
    # on a table that other tables reference with ON DELETE CASCADE.
    conn = op.get_bind()
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    try:
        with op.batch_alter_table("conversations") as batch_op:
            batch_op.alter_column("domain_id", existing_type=sa.String(36), nullable=True)

        with op.batch_alter_table("context_snapshots") as batch_op:
            batch_op.alter_column("active_domain_id", existing_type=sa.String(36), nullable=True)
    finally:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    # Any existing general (domain_id IS NULL) conversation would violate
    # the restored NOT NULL constraint — refuse rather than silently
    # deleting or reassigning real user conversations to a guessed domain.
    conn = op.get_bind()
    orphaned = conn.execute(sa.text("SELECT COUNT(*) FROM conversations WHERE domain_id IS NULL")).scalar()
    if orphaned:
        raise RuntimeError(
            f"Cannot downgrade past 0011: {orphaned} general conversation(s) with domain_id IS NULL "
            "exist and would violate the restored NOT NULL constraint. Delete or reassign them first."
        )
    orphaned_snapshots = conn.execute(
        sa.text("SELECT COUNT(*) FROM context_snapshots WHERE active_domain_id IS NULL")
    ).scalar()
    if orphaned_snapshots:
        raise RuntimeError(
            f"Cannot downgrade past 0011: {orphaned_snapshots} context_snapshot(s) with "
            "active_domain_id IS NULL exist and would violate the restored NOT NULL constraint."
        )

    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    try:
        with op.batch_alter_table("context_snapshots") as batch_op:
            batch_op.alter_column("active_domain_id", existing_type=sa.String(36), nullable=False)

        with op.batch_alter_table("conversations") as batch_op:
            batch_op.alter_column("domain_id", existing_type=sa.String(36), nullable=False)
    finally:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))
