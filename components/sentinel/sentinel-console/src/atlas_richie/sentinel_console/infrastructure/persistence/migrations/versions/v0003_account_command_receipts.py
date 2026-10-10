"""Persist safe account command receipts and versioned HMAC fingerprints."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_account_command_receipts"
down_revision = "0002_account_directory_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a minimal receipt table; raw command bodies are never stored."""
    op.create_table(
        "console_account_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("account_id", sa.String(length=36), nullable=True),
        sa.Column("account_username", sa.String(length=200), nullable=True),
        sa.Column("account_role_id", sa.String(length=16), nullable=True),
        sa.Column("account_status", sa.String(length=16), nullable=True),
        sa.Column("account_built_in", sa.Boolean(), nullable=True),
        sa.Column("account_last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("account_revision", sa.BigInteger(), nullable=True),
        sa.Column("account_last_active_admin", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_account_operation_status",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('username_taken', 'last_admin', 'built_in', 'conflict', 'not_found')",
            name="ck_console_account_operation_reason",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND account_id IS NOT NULL "
            "AND account_username IS NOT NULL AND account_role_id IN ('admin', 'view') "
            "AND account_status IN ('active', 'disabled') "
            "AND account_built_in IS NOT NULL AND account_revision IS NOT NULL "
            "AND account_revision >= 1 "
            "AND account_last_active_admin IS NOT NULL AND reason IS NULL) OR "
            "(status = 'rejected' AND account_id IS NULL "
            "AND account_username IS NULL AND account_role_id IS NULL "
            "AND account_status IS NULL AND account_built_in IS NULL "
            "AND account_last_login_at IS NULL AND account_revision IS NULL "
            "AND account_last_active_admin IS NULL AND reason IS NOT NULL)",
            name="ck_console_account_operation_result",
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("operation_id", name="uq_console_account_operation_id"),
    )
    op.create_index(
        "ix_console_account_operation_actor",
        "console_account_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Drop operation receipts after dependent application versions are removed."""
    op.drop_index(
        "ix_console_account_operation_actor", table_name="console_account_operation"
    )
    op.drop_table("console_account_operation")
