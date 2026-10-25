"""Persist enrolled Metrics V2 reporters, receipts, raw snapshots, and rollups."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0023_metrics_v2_durable_history"
down_revision = "0022_millisecond_publication_times"
branch_labels = None
depends_on = None

_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6), "mysql"
)


def upgrade() -> None:
    """Create the consumer-owned SQL history schema for Metrics V2."""
    op.create_table(
        "console_metrics_reporter_binding",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("certificate_sha256", sa.String(length=64), nullable=False),
        sa.Column("reporter_id", sa.String(length=200), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("process_id", sa.String(length=200), nullable=False),
        sa.Column("revoked_at", _PRECISE_TIMESTAMP, nullable=True),
        sa.Column("current_epoch", sa.String(length=36), nullable=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_elapsed_ns", sa.String(length=38), nullable=True),
        sa.Column("last_received_at", _PRECISE_TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "last_sequence >= 0", name="ck_console_metrics_reporter_sequence"
        ),
        sa.PrimaryKeyConstraint("certificate_principal"),
        sa.UniqueConstraint("certificate_sha256"),
        sa.UniqueConstraint("reporter_id"),
    )
    op.create_index(
        "ix_console_metrics_reporter_scope",
        "console_metrics_reporter_binding",
        ["environment_id", "app_id", "instance_id"],
    )
    op.create_table(
        "console_metrics_reporter_epoch",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("startup_epoch", sa.String(length=36), nullable=False),
        sa.Column("first_sequence", sa.BigInteger(), nullable=False),
        sa.Column("first_elapsed_ns", sa.String(length=38), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_elapsed_ns", sa.String(length=38), nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("certificate_principal", "startup_epoch"),
    )
    op.create_table(
        "console_metrics_snapshot",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("startup_epoch", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("received_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_principal", "startup_epoch"],
            [
                "console_metrics_reporter_epoch.certificate_principal",
                "console_metrics_reporter_epoch.startup_epoch",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("certificate_principal", "startup_epoch", "sequence"),
    )
    op.create_index(
        "ix_console_metrics_snapshot_received",
        "console_metrics_snapshot",
        ["received_at"],
    )
    op.create_table(
        "console_metrics_minute_rollup",
        sa.Column("rollup_id", sa.String(length=64), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("bucket_started_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("rollup_id"),
    )
    op.create_index(
        "ix_console_metrics_rollup_scope",
        "console_metrics_minute_rollup",
        ["environment_id", "app_id", "instance_id", "bucket_started_at"],
    )
    op.create_index(
        "ix_console_metrics_rollup_expiry",
        "console_metrics_minute_rollup",
        ["expires_at"],
    )


def downgrade() -> None:
    """Refuse to discard durable reporter data during schema rollback."""
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT count(*) FROM console_metrics_snapshot")
    ).scalar_one():
        raise RuntimeError(
            "cannot downgrade 0023_metrics_v2_durable_history while snapshots exist"
        )
    if bind.execute(
        sa.text("SELECT count(*) FROM console_metrics_minute_rollup")
    ).scalar_one():
        raise RuntimeError(
            "cannot downgrade 0023_metrics_v2_durable_history while rollups exist"
        )
    op.drop_index(
        "ix_console_metrics_rollup_expiry", table_name="console_metrics_minute_rollup"
    )
    op.drop_index(
        "ix_console_metrics_rollup_scope", table_name="console_metrics_minute_rollup"
    )
    op.drop_table("console_metrics_minute_rollup")
    op.drop_index(
        "ix_console_metrics_snapshot_received", table_name="console_metrics_snapshot"
    )
    op.drop_table("console_metrics_snapshot")
    op.drop_table("console_metrics_reporter_epoch")
    op.drop_index(
        "ix_console_metrics_reporter_scope",
        table_name="console_metrics_reporter_binding",
    )
    op.drop_table("console_metrics_reporter_binding")
