"""Add fenced leases for durable rule-publish work claims."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0012_rule_publish_leases"
down_revision = "0011_rule_publish_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist bounded worker claims without changing command receipts."""
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.add_column(sa.Column("work_claim_token", sa.String(length=36)))
        batch_op.add_column(
            sa.Column("work_lease_expires_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column(
                "work_attempt_count", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_work_attempts", "work_attempt_count >= 0"
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_work_lease",
            "(work_claim_token IS NULL AND work_lease_expires_at IS NULL) OR "
            "(work_claim_token IS NOT NULL AND work_lease_expires_at IS NOT NULL)",
        )
        batch_op.create_index(
            "ix_console_rule_operation_publish_queue",
            ["status", "mutation_kind", "created_at"],
        )
        batch_op.alter_column("work_attempt_count", server_default=None)


def downgrade() -> None:
    """Do not discard accepted work claims while publish operations are pending."""
    connection = op.get_bind()
    pending = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind = 'publish' AND status = 'pending'"
        )
    ).scalar_one()
    if pending:
        raise RuntimeError(
            "cannot downgrade 0012_rule_publish_leases while publish work is pending"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_index("ix_console_rule_operation_publish_queue")
        batch_op.drop_constraint("ck_console_rule_operation_work_lease", type_="check")
        batch_op.drop_constraint(
            "ck_console_rule_operation_work_attempts", type_="check"
        )
        batch_op.drop_column("work_attempt_count")
        batch_op.drop_column("work_lease_expires_at")
        batch_op.drop_column("work_claim_token")
