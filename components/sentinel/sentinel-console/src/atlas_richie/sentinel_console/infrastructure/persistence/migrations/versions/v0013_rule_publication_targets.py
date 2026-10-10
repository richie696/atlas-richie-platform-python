"""Persist exact non-secret Nacos and Consul rule targets per binding."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_rule_publication_targets"
down_revision = "0012_rule_publish_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the source-owned exact target registry used by publish commands."""
    op.create_table(
        "console_rule_publication_target",
        sa.Column("binding_id", sa.String(length=200), primary_key=True),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("target_revision", sa.String(length=200), nullable=False),
        sa.Column("source_revision", sa.String(length=200), nullable=False),
        sa.Column("target_body", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_console_rule_publication_target_source",
        "console_rule_publication_target",
        ["source_id"],
    )


def downgrade() -> None:
    """Preserve frozen targets while any accepted publish command is pending."""
    connection = op.get_bind()
    pending = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_operation "
            "WHERE mutation_kind = 'publish' AND status = 'pending'"
        )
    ).scalar_one()
    if pending:
        raise RuntimeError(
            "cannot downgrade 0013_rule_publication_targets while publish work is pending"
        )
    op.drop_index(
        "ix_console_rule_publication_target_source",
        table_name="console_rule_publication_target",
    )
    op.drop_table("console_rule_publication_target")
