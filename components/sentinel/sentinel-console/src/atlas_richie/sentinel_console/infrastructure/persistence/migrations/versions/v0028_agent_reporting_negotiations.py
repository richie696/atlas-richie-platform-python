"""Persist authenticated per-worker Agent Reporting protocol negotiations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0028_agent_reporting_negotiations"
down_revision = "0027_durable_incident_events"
branch_labels = None
depends_on = None

_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6), "mysql"
)


def upgrade() -> None:
    """Store only the latest active negotiation fact per enrolled Reporter."""
    op.create_table(
        "console_agent_reporting_negotiation",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("runtime_version", sa.String(length=200), nullable=False),
        sa.Column("collector_supported", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.String(length=16), nullable=False),
        sa.Column("observed_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "compatibility IN ('compatible', 'incompatible')",
            name="ck_console_agent_reporting_negotiation_compatibility",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("certificate_principal"),
    )
    op.create_index(
        "ix_console_agent_reporting_negotiation_observed",
        "console_agent_reporting_negotiation",
        ["observed_at"],
    )


def downgrade() -> None:
    """Retain negotiation audit facts once a deployed Runtime has used them."""
    populated = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM console_agent_reporting_negotiation"))
        .scalar_one()
    )
    if populated:
        raise RuntimeError(
            "cannot remove authenticated Agent Reporting negotiation facts"
        )
    op.drop_index(
        "ix_console_agent_reporting_negotiation_observed",
        table_name="console_agent_reporting_negotiation",
    )
    op.drop_table("console_agent_reporting_negotiation")
