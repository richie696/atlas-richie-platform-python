"""Persist rule activation plans and their original command receipts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_rule_activation_plans"
down_revision = "0008_rule_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create schedule rows and extend the finite completed-command set."""
    op.create_table(
        "console_rule_activation_plan",
        sa.Column("plan_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("version_id", sa.String(length=200), nullable=False),
        sa.Column("restore_version_id", sa.String(length=200), nullable=False),
        sa.Column("activate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deactivate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_zone", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("activation_publication_id", sa.String(length=200), nullable=True),
        sa.Column("restore_publication_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_account_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'activating', 'active', 'restoring', "
            "'completed', 'blocked', 'cancelled')",
            name="ck_console_rule_activation_plan_state",
        ),
        sa.CheckConstraint(
            "deactivate_at > activate_at",
            name="ck_console_rule_activation_plan_window",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["console_rule_version.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restore_version_id"], ["console_rule_version.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"], ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("plan_id"),
    )
    op.create_index(
        "ix_console_rule_activation_plan_binding_window",
        "console_rule_activation_plan",
        ["binding_id", "state", "activate_at", "deactivate_at"],
    )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version', 'create_plan', 'cancel_plan') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )


def downgrade() -> None:
    """Refuse to discard saved plans or completed plan-command receipts."""
    connection = op.get_bind()
    plan_count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_activation_plan")
    ).scalar_one()
    operation_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind IN ('create_plan', 'cancel_plan') AND status = 'completed'"
        )
    ).scalar_one()
    if plan_count or operation_count:
        raise RuntimeError(
            "cannot downgrade 0009_rule_activation_plans while plan history exists"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'completed' AND mutation_kind IN "
            "('save_draft', 'delete_draft', 'freeze_version') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )
    op.drop_index(
        "ix_console_rule_activation_plan_binding_window",
        table_name="console_rule_activation_plan",
    )
    op.drop_table("console_rule_activation_plan")
