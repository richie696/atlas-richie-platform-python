"""Persist only bounded, session-owned monitoring candidate check receipts."""

import sqlalchemy as sa
from alembic import op

revision = "0036_monitoring_probe_receipts"
down_revision = "0035_rule_load_observation_negotiation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the short-lived probe receipt table without endpoint/secret columns."""
    op.create_table(
        "console_monitoring_probe_receipt",
        sa.Column("check_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("source_revision", sa.String(length=200), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection", sa.String(length=16), nullable=False),
        sa.Column("query_api", sa.String(length=16), nullable=False),
        sa.Column("profile", sa.String(length=24), nullable=False),
        sa.Column("failure", sa.String(length=32), nullable=True),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("unique_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("conflicting_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "connection IN ('reachable', 'unreachable')",
            name="ck_console_monitoring_probe_connection",
        ),
        sa.CheckConstraint(
            "query_api IN ('available', 'denied', 'unsupported', 'unknown')",
            name="ck_console_monitoring_probe_query_api",
        ),
        sa.CheckConstraint(
            "profile IN ('supported', 'missing_samples', 'unsupported', 'unknown')",
            name="ck_console_monitoring_probe_profile",
        ),
        sa.CheckConstraint(
            "failure IS NULL OR failure IN "
            "('target_rejected', 'authentication', 'timeout', 'transport', 'invalid_response')",
            name="ck_console_monitoring_probe_failure",
        ),
        sa.CheckConstraint(
            "observed_count >= 0 AND unique_count >= 0 AND missing_count >= 0 "
            "AND conflicting_count >= 0 AND observed_count <= 10000 "
            "AND unique_count + missing_count + conflicting_count <= observed_count",
            name="ck_console_monitoring_probe_counts",
        ),
        sa.CheckConstraint(
            "expires_at > checked_at",
            name="ck_console_monitoring_probe_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"],
            ["console_account.account_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("check_id"),
    )
    op.create_index(
        "ix_console_monitoring_probe_expiry",
        "console_monitoring_probe_receipt",
        ["expires_at"],
    )
    op.create_index(
        "ix_console_monitoring_probe_owner",
        "console_monitoring_probe_receipt",
        ["actor_account_id", "session_hash", "checked_at"],
    )


def downgrade() -> None:
    """Remove monitoring candidate receipts and their indexes."""
    op.drop_index(
        "ix_console_monitoring_probe_owner",
        table_name="console_monitoring_probe_receipt",
    )
    op.drop_index(
        "ix_console_monitoring_probe_expiry",
        table_name="console_monitoring_probe_receipt",
    )
    op.drop_table("console_monitoring_probe_receipt")
