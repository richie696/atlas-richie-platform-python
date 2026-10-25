"""Retain reporter/resource identity in per-reporter minute rollups."""

import sqlalchemy as sa
from alembic import op

revision = "0024_metrics_rollup_reporter_scope"
down_revision = "0023_metrics_v2_durable_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable identity dimensions without rewriting prior rollup facts."""
    op.add_column(
        "console_metrics_minute_rollup",
        sa.Column("reporter_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "console_metrics_minute_rollup",
        sa.Column("startup_epoch", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "console_metrics_minute_rollup",
        sa.Column("resource_id", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_console_metrics_rollup_reporter_scope",
        "console_metrics_minute_rollup",
        ["reporter_id", "startup_epoch", "metric_name", "bucket_started_at"],
    )


def downgrade() -> None:
    """Refuse to discard reporter/resource rollup identity once populated."""
    populated = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM console_metrics_minute_rollup "
                "WHERE reporter_id IS NOT NULL OR startup_epoch IS NOT NULL "
                "OR resource_id IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if populated:
        raise RuntimeError(
            "cannot remove Metrics rollup identity while rollup facts exist"
        )
    op.drop_index(
        "ix_console_metrics_rollup_reporter_scope",
        table_name="console_metrics_minute_rollup",
    )
    op.drop_column("console_metrics_minute_rollup", "resource_id")
    op.drop_column("console_metrics_minute_rollup", "startup_epoch")
    op.drop_column("console_metrics_minute_rollup", "reporter_id")
