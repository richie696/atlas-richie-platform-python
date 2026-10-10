"""Persist safe, immutable profile-validation receipts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_rule_validation_receipts"
down_revision = "0004_login_attempt_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the receipt table without storing candidate rule contents."""
    op.create_table(
        "console_rule_validation_receipt",
        sa.Column("validation_id", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("profile", sa.String(length=200), nullable=False),
        sa.Column("base_checksum", sa.String(length=200), nullable=False),
        sa.Column("candidate_checksum", sa.String(length=200), nullable=False),
        sa.Column("is_publishable", sa.Boolean(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "is_publishable IN (false, true)",
            name="ck_console_rule_validation_publishable",
        ),
        sa.PrimaryKeyConstraint("validation_id"),
    )
    op.create_index(
        "ix_console_rule_validation_binding_created",
        "console_rule_validation_receipt",
        ["binding_id", "created_at"],
    )


def downgrade() -> None:
    """Remove validation receipts when rolling back this schema revision."""
    op.drop_index(
        "ix_console_rule_validation_binding_created",
        table_name="console_rule_validation_receipt",
    )
    op.drop_table("console_rule_validation_receipt")
