"""Persist bounded, hashed login-attempt state for shared worker enforcement."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_login_attempt_limits"
down_revision = "0003_account_command_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the login limiter table without storing raw addresses or usernames."""
    op.create_table(
        "console_login_attempt",
        sa.Column("client_identity_digest", sa.String(length=64), nullable=False),
        sa.Column("window_started_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("blocked_until_ms", sa.BigInteger(), nullable=True),
        sa.Column("expires_at_ms", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "failure_count >= 0", name="ck_console_login_attempt_count"
        ),
        sa.PrimaryKeyConstraint("client_identity_digest"),
    )
    op.create_index(
        "ix_console_login_attempt_expiry",
        "console_login_attempt",
        ["expires_at_ms"],
    )


def downgrade() -> None:
    """Drop persisted login-attempt state."""
    op.drop_index(
        "ix_console_login_attempt_expiry", table_name="console_login_attempt"
    )
    op.drop_table("console_login_attempt")
