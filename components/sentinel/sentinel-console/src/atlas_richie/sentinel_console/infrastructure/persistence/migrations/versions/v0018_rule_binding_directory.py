"""Persist rule-binding metadata separately from provider rule contents."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_rule_binding_directory"
down_revision = "0017_scheduled_rule_publication_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the Console-owned app/environment/type binding directory."""
    op.create_table(
        "console_rule_binding",
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=200), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_binding_kind",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["console_registered_source.source_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("binding_id"),
        sa.UniqueConstraint(
            "environment_id",
            "app_id",
            "kind",
            name="uq_console_rule_binding_scope_kind",
        ),
    )
    op.create_index(
        "ix_console_rule_binding_scope",
        "console_rule_binding",
        ["environment_id", "app_id", "kind"],
    )


def downgrade() -> None:
    """Refuse removal if durable rules or publications refer to a binding."""
    connection = op.get_bind()
    binding_count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_binding")
    ).scalar_one()
    if binding_count:
        raise RuntimeError(
            "cannot downgrade 0018_rule_binding_directory while bindings exist"
        )
    op.drop_index("ix_console_rule_binding_scope", table_name="console_rule_binding")
    op.drop_table("console_rule_binding")
