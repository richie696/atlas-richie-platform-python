"""Preserve account history while supporting soft deletion and admin lifecycle commands."""

from alembic import op
import sqlalchemy as sa

revision = "0041_account_lifecycle"
down_revision = "0040_monitoring_source_in_use"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Existing identities remain live; new lifecycle receipts retain stable reasons."""
    op.add_column("console_account", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("console_account_operation") as batch:
        batch.drop_constraint("ck_console_account_operation_reason", type_="check")
        batch.create_check_constraint(
            "ck_console_account_operation_reason",
            "reason IS NULL OR reason IN "
            "('username_taken', 'last_admin', 'built_in', 'conflict', 'not_found', 'self_operation')",
        )


def downgrade() -> None:
    """A tombstone must never become a live account through schema rollback."""
    raise RuntimeError("account lifecycle tombstones and receipts cannot be safely downgraded")
