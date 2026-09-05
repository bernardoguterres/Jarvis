"""Phase 9 correction: replace the legacy Fitbit Web API integration with
the current Google Health API. Forward-only — 0005 is left untouched.

Renames fitbit_daily_summaries -> google_health_daily_summaries (data
preserved), renames context_snapshots.fitbit_summary_ids_json ->
google_health_summary_ids_json, and updates the integration_connections
provider CHECK constraint to ('google_calendar', 'google_health').

Any pre-existing legacy 'fitbit' row in integration_connections is removed
before the constraint is tightened: no real Fitbit account was ever
connected on this installation, 'fitbit' is not preserved as a selectable
provider going forward, and no legacy token is ever reused or reinterpreted
as a Google credential (tokens live only in Keychain, never in this table,
so there is nothing to migrate there). The cached daily-summary data itself
is preserved via the table rename below, independent of the connection row.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-26

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove any legacy 'fitbit' connection row so it cannot violate the
    # tightened provider CHECK constraint below. No token is read or moved —
    # OAuth credentials never lived in this table (Keychain-only).
    op.execute("DELETE FROM integration_connections WHERE provider = 'fitbit'")

    op.rename_table("fitbit_daily_summaries", "google_health_daily_summaries")
    op.drop_index("ix_fitbit_daily_summaries_date", table_name="google_health_daily_summaries")
    op.create_index("ix_google_health_daily_summaries_date", "google_health_daily_summaries", ["date"])
    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.drop_constraint("uq_fitbit_daily_summaries_date", type_="unique")
        batch_op.create_unique_constraint("uq_google_health_daily_summaries_date", ["date"])

    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.alter_column(
            "fitbit_summary_ids_json",
            new_column_name="google_health_summary_ids_json",
        )

    with op.batch_alter_table("integration_connections") as batch_op:
        batch_op.drop_constraint("ck_integration_connections_provider_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_integration_connections_provider_valid",
            "provider IN ('google_calendar', 'google_health')",
        )


def downgrade() -> None:
    with op.batch_alter_table("integration_connections") as batch_op:
        batch_op.drop_constraint("ck_integration_connections_provider_valid", type_="check")
        batch_op.create_check_constraint(
            "ck_integration_connections_provider_valid",
            "provider IN ('google_calendar', 'fitbit')",
        )

    with op.batch_alter_table("context_snapshots") as batch_op:
        batch_op.alter_column(
            "google_health_summary_ids_json",
            new_column_name="fitbit_summary_ids_json",
        )

    with op.batch_alter_table("google_health_daily_summaries") as batch_op:
        batch_op.drop_constraint("uq_google_health_daily_summaries_date", type_="unique")
        batch_op.create_unique_constraint("uq_fitbit_daily_summaries_date", ["date"])
    op.drop_index("ix_google_health_daily_summaries_date", table_name="google_health_daily_summaries")
    op.rename_table("google_health_daily_summaries", "fitbit_daily_summaries")
    op.create_index("ix_fitbit_daily_summaries_date", "fitbit_daily_summaries", ["date"])
