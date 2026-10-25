"""Persist bounded current rule-source projections for the Console catalog."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_rule_catalog_projection"
down_revision = "0033_receipt_projection_ordering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create SQL-searchable rule rows and last-read freshness per binding."""
    op.create_table(
        "console_rule_catalog_snapshot",
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("read_state", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checksum", sa.String(length=72), nullable=True),
        sa.Column("source_revision", sa.String(length=200), nullable=True),
        sa.Column("version_id", sa.String(length=200), nullable=True),
        sa.Column("rule_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "read_state IN ('current', 'stale', 'unavailable')",
            name="ck_console_rule_catalog_read_state",
        ),
        sa.CheckConstraint("rule_count >= 0", name="ck_console_rule_catalog_rule_count"),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["console_rule_binding.binding_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    op.create_index(
        "ix_console_rule_catalog_scope",
        "console_rule_catalog_snapshot",
        ["environment_id", "app_id"],
    )
    op.create_table(
        "console_rule_catalog_rule",
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("rule_id", sa.String(length=200), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("resource_search", sa.Text(), nullable=False),
        sa.Column("rule_body", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["console_rule_binding.binding_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("binding_id", "rule_id"),
    )
    op.create_index(
        "ix_console_rule_catalog_rule_scope",
        "console_rule_catalog_rule",
        ["environment_id", "app_id", "kind", "binding_id"],
    )


def downgrade() -> None:
    """Keep projections rather than silently erasing an operator's read history."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_catalog_snapshot")
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade while rule catalog projections exist")
    op.drop_index(
        "ix_console_rule_catalog_rule_scope", table_name="console_rule_catalog_rule"
    )
    op.drop_table("console_rule_catalog_rule")
    op.drop_index("ix_console_rule_catalog_scope", table_name="console_rule_catalog_snapshot")
    op.drop_table("console_rule_catalog_snapshot")
