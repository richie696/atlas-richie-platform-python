"""Represent scheduled publication execution without a browser session."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0017_scheduled_rule_publication_origin"
down_revision = "0016_rule_activation_plan_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Attach durable scheduled work to its plan, not a fabricated account session."""
    # Alembic's default version table is VARCHAR(32), but this revision ID is
    # longer. PostgreSQL/MySQL enforce that limit when Alembic records the new
    # head after this function returns, so widen the storage before that update.
    if op.get_bind().dialect.name in {"postgresql", "mysql"}:
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )

    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.alter_column(
            "session_hash",
            existing_type=sa.String(length=64),
            nullable=True,
        )
        batch_op.add_column(sa.Column("origin_plan_id", sa.String(length=200)))
        batch_op.add_column(sa.Column("origin_phase", sa.String(length=16)))
        batch_op.create_foreign_key(
            "fk_console_rule_operation_origin_plan",
            "console_rule_activation_plan",
            ["origin_plan_id"],
            ["plan_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_actor_origin",
            "(actor_account_id IS NOT NULL AND session_hash IS NOT NULL "
            "AND origin_plan_id IS NULL AND origin_phase IS NULL) OR "
            "(actor_account_id IS NULL AND session_hash IS NULL "
            "AND origin_plan_id IS NOT NULL "
            "AND origin_phase IN ('activation', 'restoration'))",
        )
        batch_op.create_check_constraint(
            "ck_console_rule_operation_plan_phase",
            "(origin_plan_id IS NULL AND origin_phase IS NULL) OR "
            "(origin_plan_id IS NOT NULL AND origin_phase IS NOT NULL "
            "AND mutation_kind = 'publish')",
        )
        batch_op.create_unique_constraint(
            "uq_console_rule_operation_plan_phase",
            ["origin_plan_id", "origin_phase"],
        )


def downgrade() -> None:
    """Refuse rollback while scheduled work still relies on sessionless rows."""
    connection = op.get_bind()
    scheduled = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE origin_plan_id IS NOT NULL"
        )
    ).scalar_one()
    if scheduled:
        raise RuntimeError(
            "cannot downgrade while scheduled rule publication operations exist"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("uq_console_rule_operation_plan_phase", type_="unique")
        batch_op.drop_constraint("ck_console_rule_operation_plan_phase", type_="check")
        batch_op.drop_constraint("ck_console_rule_operation_actor_origin", type_="check")
        batch_op.drop_constraint("fk_console_rule_operation_origin_plan", type_="foreignkey")
        batch_op.drop_column("origin_phase")
        batch_op.drop_column("origin_plan_id")
        batch_op.alter_column(
            "session_hash",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.alter_column(
            "actor_account_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
