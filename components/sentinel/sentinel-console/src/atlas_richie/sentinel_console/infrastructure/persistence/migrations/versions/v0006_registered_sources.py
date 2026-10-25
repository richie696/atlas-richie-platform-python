"""Persist configuration-source registry, encrypted credentials and receipts."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_registered_sources"
down_revision = "0005_rule_validation_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create registry and idempotency facts without storing command secrets."""
    op.create_table(
        "console_registered_source",
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("authentication_mode", sa.String(length=32), nullable=False),
        sa.Column("credential_configured", sa.Boolean(), nullable=False),
        sa.Column("credential_cipher_format", sa.String(length=32), nullable=True),
        sa.Column("credential_key_id", sa.String(length=64), nullable=True),
        sa.Column("credential_payload", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_account_id", sa.String(length=36), nullable=False),
        sa.CheckConstraint(
            "provider IN ('nacos', 'consul')",
            name="ck_console_registered_source_provider",
        ),
        sa.CheckConstraint(
            "authentication_mode IN ('none', 'credential-reference', 'direct')",
            name="ck_console_registered_source_auth_mode",
        ),
        sa.CheckConstraint(
            "(authentication_mode = 'none' AND credential_configured = false "
            "AND credential_cipher_format IS NULL AND credential_key_id IS NULL "
            "AND credential_payload IS NULL) OR "
            "(authentication_mode IN ('credential-reference', 'direct') "
            "AND credential_configured = true "
            "AND credential_cipher_format IS NOT NULL "
            "AND credential_key_id IS NOT NULL AND credential_payload IS NOT NULL)",
            name="ck_console_registered_source_credential_envelope",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_account_id"],
            ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index(
        "ix_console_registered_source_provider",
        "console_registered_source",
        ["provider", "source_id"],
    )
    op.create_table(
        "console_registered_source_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.String(length=200), nullable=True),
        sa.Column("source_revision", sa.String(length=200), nullable=True),
        sa.Column("source_name", sa.String(length=200), nullable=True),
        sa.Column("source_endpoint", sa.String(length=2048), nullable=True),
        sa.Column("source_provider", sa.String(length=16), nullable=True),
        sa.Column("source_location", sa.String(length=200), nullable=True),
        sa.Column("source_authentication_mode", sa.String(length=32), nullable=True),
        sa.Column("source_credential_configured", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('completed', 'rejected')",
            name="ck_console_registered_source_operation_status",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('validation', 'conflict', 'not_found', 'unavailable')",
            name="ck_console_registered_source_operation_reason",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND reason IS NULL AND source_id IS NOT NULL "
            "AND source_revision IS NOT NULL AND source_name IS NOT NULL "
            "AND source_endpoint IS NOT NULL "
            "AND source_provider IN ('nacos', 'consul') "
            "AND source_location IS NOT NULL "
            "AND source_authentication_mode IS NOT NULL "
            "AND source_credential_configured IS NOT NULL) OR "
            "(status = 'rejected' AND reason IS NOT NULL AND source_id IS NULL "
            "AND source_revision IS NULL AND source_name IS NULL "
            "AND source_endpoint IS NULL AND source_provider IS NULL "
            "AND source_location IS NULL AND source_authentication_mode IS NULL "
            "AND source_credential_configured IS NULL)",
            name="ck_console_registered_source_operation_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["console_account.account_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint(
            "operation_id", name="uq_console_registered_source_operation_id"
        ),
    )
    op.create_index(
        "ix_console_registered_source_operation_actor",
        "console_registered_source_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    """Remove source facts and receipts in dependency order."""
    op.drop_index(
        "ix_console_registered_source_operation_actor",
        table_name="console_registered_source_operation",
    )
    op.drop_table("console_registered_source_operation")
    op.drop_index(
        "ix_console_registered_source_provider",
        table_name="console_registered_source",
    )
    op.drop_table("console_registered_source")
