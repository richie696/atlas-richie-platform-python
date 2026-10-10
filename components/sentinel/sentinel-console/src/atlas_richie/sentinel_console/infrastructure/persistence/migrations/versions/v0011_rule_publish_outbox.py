"""Persist accepted publish commands as work recoverable after process restart."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_rule_publish_outbox"
down_revision = "0010_rule_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow an accepted publish operation to be durably pending with intent."""
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.add_column(
            sa.Column("work_payload", sa.JSON(none_as_null=True), nullable=True)
        )
        batch_op.drop_constraint("ck_console_rule_operation_status", type_="check")
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_status",
            "status IN ('pending', 'completed', 'rejected')",
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'pending' AND mutation_kind = 'publish' "
            "AND reason IS NULL AND result IS NULL AND work_payload IS NOT NULL) OR "
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'publish', 'create_plan', 'cancel_plan') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )


def downgrade() -> None:
    """Refuse to discard accepted provider work or completed publications."""
    connection = op.get_bind()
    pending = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind = 'publish' AND status = 'pending'"
        )
    ).scalar_one()
    publications = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_publication")
    ).scalar_one()
    if pending or publications:
        raise RuntimeError(
            "cannot downgrade 0011_rule_publish_outbox while publish work exists"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.drop_constraint("ck_console_rule_operation_status", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_status",
            "status IN ('completed', 'rejected')",
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'create_plan', 'cancel_plan') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )
        batch_op.drop_column("work_payload")
