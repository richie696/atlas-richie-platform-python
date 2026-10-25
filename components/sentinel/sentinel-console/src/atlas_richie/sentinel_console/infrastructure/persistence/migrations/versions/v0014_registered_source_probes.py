"""Persist current-revision registered-source connectivity observations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_registered_source_probes"
down_revision = "0013_rule_publication_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create a bounded, secret-free latest-probe record per registered source."""
    op.create_table(
        "console_registered_source_probe",
        sa.Column(
            "source_id",
            sa.String(length=200),
            sa.ForeignKey("console_registered_source.source_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.String(length=200), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('connection', 'authentication', 'unsupported')",
            name="ck_console_registered_source_probe_reason",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name="ck_console_registered_source_probe_latency",
        ),
        sa.CheckConstraint(
            "expires_at > checked_at",
            name="ck_console_registered_source_probe_expiry",
        ),
    )
    op.create_index(
        "ix_console_registered_source_probe_expiry",
        "console_registered_source_probe",
        ["expires_at"],
    )


def downgrade() -> None:
    """Drop only the ephemeral latest-probe cache, never source configuration."""
    op.drop_index(
        "ix_console_registered_source_probe_expiry",
        table_name="console_registered_source_probe",
    )
    op.drop_table("console_registered_source_probe")
