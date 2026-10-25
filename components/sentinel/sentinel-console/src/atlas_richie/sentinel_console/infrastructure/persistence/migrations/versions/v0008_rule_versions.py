"""Persist immutable validated rule versions and freeze receipts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_rule_versions"
down_revision = "0007_rule_drafts_and_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the immutable version table and permit completed freeze receipts."""
    op.create_table(
        "console_rule_version",
        sa.Column("version_id", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=200), nullable=False),
        sa.Column("base_version_id", sa.String(length=200), nullable=True),
        sa.Column("checksum", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=False),
        sa.Column("validation_id", sa.String(length=200), nullable=False),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_account_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_version_kind",
        ),
        sa.ForeignKeyConstraint(
            ["validation_id"],
            ["console_rule_validation_receipt.validation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_account_id"],
            ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index(
        "ix_console_rule_version_binding_created",
        "console_rule_version",
        ["binding_id", "created_at"],
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


def downgrade() -> None:
    """Remove the extension only when no immutable version history exists."""
    connection = op.get_bind()
    version_count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_version")
    ).scalar_one()
    freeze_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind = 'freeze_version' AND status = 'completed'"
        )
    ).scalar_one()
    if version_count or freeze_count:
        raise RuntimeError(
            "cannot downgrade 0008_rule_versions while immutable version history exists"
        )
    with op.batch_alter_table("console_rule_operation") as batch_op:
        batch_op.drop_constraint("ck_console_rule_operation_result", type_="check")
        batch_op.create_check_constraint(
            "ck_console_rule_operation_result",
            "(status = 'completed' AND mutation_kind IN ('save_draft', 'delete_draft') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
        )
    op.drop_index(
        "ix_console_rule_version_binding_created",
        table_name="console_rule_version",
    )
    op.drop_table("console_rule_version")
