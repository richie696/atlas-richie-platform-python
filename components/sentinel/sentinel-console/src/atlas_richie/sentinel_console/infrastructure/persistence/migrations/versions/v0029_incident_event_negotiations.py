"""Persist authenticated Incident Event version negotiation per worker."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0029_incident_event_negotiations"
down_revision = "0028_agent_reporting_negotiations"
branch_labels = None
depends_on = None

_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6), "mysql"
)


def upgrade() -> None:
    """Add an independent fact table; never overwrite Agent Reporting state."""
    op.create_table(
        "console_incident_event_negotiation",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("runtime_version", sa.String(length=200), nullable=False),
        sa.Column("collector_supported", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.String(length=16), nullable=False),
        sa.Column("observed_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "compatibility IN ('compatible', 'incompatible')",
            name="ck_console_incident_event_negotiation_compatibility",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("certificate_principal"),
    )
    op.create_index(
        "ix_console_incident_event_negotiation_observed",
        "console_incident_event_negotiation",
        ["observed_at"],
    )


def downgrade() -> None:
    """Refuse to discard deployed authenticated negotiation facts."""
    populated = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM console_incident_event_negotiation"))
        .scalar_one()
    )
    if populated:
        raise RuntimeError(
            "cannot remove authenticated Incident Event negotiation facts"
        )
    op.drop_index(
        "ix_console_incident_event_negotiation_observed",
        table_name="console_incident_event_negotiation",
    )
    op.drop_table("console_incident_event_negotiation")
