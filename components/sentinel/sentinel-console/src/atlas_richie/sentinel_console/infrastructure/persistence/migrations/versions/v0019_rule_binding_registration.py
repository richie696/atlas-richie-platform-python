"""Persist idempotent receipts for exact rule-binding registration."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0019_rule_binding_registration"
down_revision = "0018_rule_binding_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add actor/session-bound create receipts without rule content."""
    op.create_table(
        "console_rule_binding_registration_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["console_account.account_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["console_rule_binding.binding_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("binding_id"),
    )
    op.create_index(
        "ix_console_rule_binding_registration_actor",
        "console_rule_binding_registration_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Refuse to discard durable operation receipts after binding creation."""
    connection = op.get_bind()
    operation_count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_binding_registration_operation")
    ).scalar_one()
    if operation_count:
        raise RuntimeError(
            "cannot downgrade 0019_rule_binding_registration while receipts exist"
        )
    op.drop_index(
        "ix_console_rule_binding_registration_actor",
        table_name="console_rule_binding_registration_operation",
    )
    op.drop_table("console_rule_binding_registration_operation")
