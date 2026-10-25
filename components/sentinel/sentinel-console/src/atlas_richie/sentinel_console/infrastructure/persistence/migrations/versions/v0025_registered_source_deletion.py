"""Add metadata-free, idempotent receipts for registered-source deletion."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0025_registered_source_deletion"
down_revision = "0024_metrics_rollup_reporter_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Store only the deletion outcome and opaque source identity."""
    op.create_table(
        "console_registered_source_deletion_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("deleted_source_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_registered_source_deletion_status",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('conflict', 'not_found', 'source_in_use')",
            name="ck_console_registered_source_deletion_reason",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND reason IS NULL AND deleted_source_id IS NOT NULL) OR "
            "(status = 'rejected' AND reason IS NOT NULL AND deleted_source_id IS NULL)",
            name="ck_console_registered_source_deletion_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["console_account.account_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint(
            "operation_id", name="uq_console_registered_source_deletion_operation_id"
        ),
    )
    op.create_index(
        "ix_console_registered_source_deletion_actor",
        "console_registered_source_deletion_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Keep durable delete receipts; this safety migration is intentionally irreversible."""
    raise RuntimeError(
        "cannot remove registered-source deletion receipts after API 0.5.0 use"
    )
