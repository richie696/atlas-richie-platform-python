"""Add safe account-directory facts with conservative existing-row defaults."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_account_directory_facts"
down_revision = "0001_identity_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add built-in and last-login facts without changing existing accounts."""
    with op.batch_alter_table("console_account") as batch_op:
        batch_op.add_column(
            sa.Column(
                "built_in", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_console_account_builtin_admin_active",
            "built_in = false OR (role_id = 'admin' AND status = 'active')",
        )


def downgrade() -> None:
    """Remove the additive account-directory facts."""
    with op.batch_alter_table("console_account") as batch_op:
        batch_op.drop_constraint(
            "ck_console_account_builtin_admin_active", type_="check"
        )
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("built_in")
