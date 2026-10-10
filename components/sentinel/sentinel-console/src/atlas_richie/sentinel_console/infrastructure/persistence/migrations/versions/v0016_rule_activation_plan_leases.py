"""Add fenced leases for scheduled rule activation work."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_rule_activation_plan_leases"
down_revision = "0015_rule_target_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist due-plan claims so workers can recover after process restarts."""
    with op.batch_alter_table("console_rule_activation_plan") as batch_op:
        batch_op.add_column(sa.Column("claim_token", sa.String(length=36)))
        batch_op.add_column(
            sa.Column("claim_lease_expires_at", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column(
                "claim_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_console_rule_activation_plan_claim_attempts",
            "claim_attempt_count >= 0",
        )
        batch_op.create_check_constraint(
            "ck_console_rule_activation_plan_claim_lease",
            "(claim_token IS NULL AND claim_lease_expires_at IS NULL) OR "
            "(claim_token IS NOT NULL AND claim_lease_expires_at IS NOT NULL)",
        )
        batch_op.create_index(
            "ix_console_rule_activation_plan_due",
            ["state", "activate_at", "deactivate_at", "claim_lease_expires_at"],
        )
        batch_op.alter_column("claim_attempt_count", server_default=None)


def downgrade() -> None:
    """Do not remove an active claim while a worker may still be executing it."""
    connection = op.get_bind()
    claimed = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_activation_plan "
            "WHERE claim_token IS NOT NULL"
        )
    ).scalar_one()
    if claimed:
        raise RuntimeError(
            "cannot downgrade 0016_rule_activation_plan_leases while claims exist"
        )
    with op.batch_alter_table("console_rule_activation_plan") as batch_op:
        batch_op.drop_index("ix_console_rule_activation_plan_due")
        batch_op.drop_constraint(
            "ck_console_rule_activation_plan_claim_lease", type_="check"
        )
        batch_op.drop_constraint(
            "ck_console_rule_activation_plan_claim_attempts", type_="check"
        )
        batch_op.drop_column("claim_attempt_count")
        batch_op.drop_column("claim_lease_expires_at")
        batch_op.drop_column("claim_token")
