"""Persist authenticated Incident Event V1 facts and durable receipts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0027_durable_incident_events"
down_revision = "0026_metrics_worker_instance_identity"
branch_labels = None
depends_on = None

_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6), "mysql"
)


def upgrade() -> None:
    """Create a bounded, append-only incident fact table."""
    op.create_table(
        "console_incident_event",
        sa.Column("incident_id", sa.String(length=64), nullable=False),
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("process_id", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("received_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("fact_payload", sa.JSON(), nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_console_incident_severity",
        ),
        sa.CheckConstraint(
            "category IN ('resource', 'rt')",
            name="ck_console_incident_category",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("incident_id"),
        sa.UniqueConstraint(
            "certificate_principal",
            "event_id",
            name="uq_console_incident_reporter_event",
        ),
    )
    op.create_index(
        "ix_console_incident_scope_time",
        "console_incident_event",
        [
            "environment_id",
            "app_id",
            "instance_id",
            "occurred_at",
            "incident_id",
        ],
    )
    op.create_index(
        "ix_console_incident_expiry",
        "console_incident_event",
        ["expires_at"],
    )


def downgrade() -> None:
    """Refuse to discard the durable incident timeline after it has data."""
    populated = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM console_incident_event"))
        .scalar_one()
    )
    if populated:
        raise RuntimeError("cannot downgrade 0027 while durable incident facts exist")
    op.drop_index("ix_console_incident_expiry", table_name="console_incident_event")
    op.drop_index("ix_console_incident_scope_time", table_name="console_incident_event")
    op.drop_table("console_incident_event")
