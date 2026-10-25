"""Persist mutable rule drafts and actor-bound command receipts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_rule_drafts_and_commands"
down_revision = "0006_registered_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add complete draft snapshots and immutable idempotency receipts."""
    op.create_table(
        "console_rule_draft",
        sa.Column("draft_id", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=200), nullable=False),
        sa.Column("base_version_id", sa.String(length=200), nullable=True),
        sa.Column("base_checksum", sa.String(length=200), nullable=False),
        sa.Column("source_revision", sa.String(length=200), nullable=True),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_account_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flow', 'degrade', 'system', 'authority', 'param')",
            name="ck_console_rule_draft_kind",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("draft_id"),
    )
    op.create_index(
        "ix_console_rule_draft_binding_updated",
        "console_rule_draft",
        ["binding_id", "updated_at"],
    )
    op.create_table(
        "console_rule_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("mutation_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_rule_operation_status",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('validation', 'conflict', 'not_found', 'unsupported', 'unavailable')",
            name="ck_console_rule_operation_reason",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND mutation_kind IN ('save_draft', 'delete_draft') "
            "AND reason IS NULL AND result IS NOT NULL) OR "
            "(status = 'rejected' AND mutation_kind IS NOT NULL "
            "AND reason IS NOT NULL AND result IS NULL)",
            name="ck_console_rule_operation_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("operation_id", name="uq_console_rule_operation_id"),
    )
    op.create_index(
        "ix_console_rule_operation_actor",
        "console_rule_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Remove rule operation receipts before the mutable draft table."""
    op.drop_index(
        "ix_console_rule_operation_actor", table_name="console_rule_operation"
    )
    op.drop_table("console_rule_operation")
    op.drop_index(
        "ix_console_rule_draft_binding_updated", table_name="console_rule_draft"
    )
    op.drop_table("console_rule_draft")
