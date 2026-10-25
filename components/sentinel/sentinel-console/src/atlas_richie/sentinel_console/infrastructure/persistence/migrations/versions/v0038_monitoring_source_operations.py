"""Persist idempotent monitoring-source management operation receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0038_monitoring_source_operations"
down_revision = "0037_monitoring_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create actor/session-bound receipts without request secrets or endpoints."""
    op.create_table(
        "console_monitoring_source_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.String(length=200), nullable=True),
        sa.Column("source_revision", sa.String(length=200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_monitoring_source_operation_status",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('conflict', 'not_found', 'check_required', 'check_mismatch')",
            name="ck_console_monitoring_source_operation_reason",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND reason IS NULL AND source_id IS NOT NULL) OR "
            "(status = 'rejected' AND reason IS NOT NULL)",
            name="ck_console_monitoring_source_operation_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["console_account.account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("operation_id"),
    )
    op.create_index(
        "ix_console_monitoring_source_operation_actor",
        "console_monitoring_source_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Drop monitoring-source command receipts."""
    op.drop_index(
        "ix_console_monitoring_source_operation_actor",
        table_name="console_monitoring_source_operation",
    )
    op.drop_table("console_monitoring_source_operation")
