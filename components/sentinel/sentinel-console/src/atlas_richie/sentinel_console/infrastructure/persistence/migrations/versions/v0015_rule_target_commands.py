"""Allow durable, audited rule-publication target configuration commands."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_rule_target_commands"
down_revision = "0014_registered_source_probes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Extend completed command receipts with the credential-free target result."""
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'pending' AND mutation_kind = 'publish' "
            "AND reason IS NULL AND result IS NULL AND work_payload IS NOT NULL) OR "
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'publish', "
            "'create_plan', 'cancel_plan', 'configure_target') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )


def downgrade() -> None:
    """Protect completed target command receipts from incompatible downgrade."""
    connection = op.get_bind()
    configured = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind = 'configure_target'"
        )
    ).scalar_one()
    if configured:
        raise RuntimeError(
            "cannot downgrade 0015_rule_target_commands while target receipts exist"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'pending' AND mutation_kind = 'publish' "
            "AND reason IS NULL AND result IS NULL AND work_payload IS NOT NULL) OR "
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'publish', "
            "'create_plan', 'cancel_plan') AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )

