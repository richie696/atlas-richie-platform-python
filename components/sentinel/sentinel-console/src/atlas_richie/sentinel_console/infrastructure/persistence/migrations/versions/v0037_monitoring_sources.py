"""Persist independent monitoring sources with encrypted credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0037_monitoring_sources"
down_revision = "0036_monitoring_probe_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a monitoring-source registry distinct from rule-source records."""
    op.create_table(
        "console_monitoring_source",
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("authentication_mode", sa.String(length=32), nullable=False),
        sa.Column("credential_configured", sa.Boolean(), nullable=False),
        sa.Column("credential_cipher_format", sa.String(length=32), nullable=True),
        sa.Column("credential_key_id", sa.String(length=64), nullable=True),
        sa.Column("credential_payload", sa.LargeBinary(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("identity_labels", sa.JSON(), nullable=False),
        sa.Column("selector_labels", sa.JSON(), nullable=False),
        sa.Column("scrape_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider = 'prometheus-compatible'",
            name="ck_console_monitoring_source_provider",
        ),
        sa.CheckConstraint(
            "profile = 'node-exporter-v1'",
            name="ck_console_monitoring_source_profile",
        ),
        sa.CheckConstraint(
            "authentication_mode IN ('none', 'direct-basic', 'direct-bearer', 'credential-reference')",
            name="ck_console_monitoring_source_auth_mode",
        ),
        sa.CheckConstraint(
            "(authentication_mode = 'none' AND credential_configured = false "
            "AND credential_cipher_format IS NULL AND credential_key_id IS NULL "
            "AND credential_payload IS NULL) OR "
            "(authentication_mode <> 'none' AND credential_configured = true "
            "AND credential_cipher_format IS NOT NULL AND credential_key_id IS NOT NULL "
            "AND credential_payload IS NOT NULL)",
            name="ck_console_monitoring_source_credential_envelope",
        ),
        sa.CheckConstraint(
            "scrape_interval_seconds BETWEEN 1 AND 300",
            name="ck_console_monitoring_source_scrape_interval",
        ),
        sa.CheckConstraint(
            "stale_after_seconds > scrape_interval_seconds AND stale_after_seconds <= 3600",
            name="ck_console_monitoring_source_stale_after",
        ),
        sa.PrimaryKeyConstraint("source_id"),
    )
    op.create_index(
        "ix_console_monitoring_source_scope",
        "console_monitoring_source",
        ["environment_id", "enabled", "display_name"],
    )


def downgrade() -> None:
    """Drop monitoring source metadata and encrypted credentials."""
    op.drop_index(
        "ix_console_monitoring_source_scope",
        table_name="console_monitoring_source",
    )
    op.drop_table("console_monitoring_source")
