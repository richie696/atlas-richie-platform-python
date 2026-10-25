"""Persist authenticated Rule Load Observation negotiation facts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

revision = "0035_rule_load_observation_negotiation"
down_revision = "0034_rule_load_observations"
branch_labels = None
depends_on = None

_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=6), "mysql"
)


def upgrade() -> None:
    op.create_table(
        "console_rule_load_observation_negotiation",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("runtime_version", sa.String(length=200), nullable=False),
        sa.Column("collector_supported", sa.JSON(), nullable=False),
        sa.Column("compatibility", sa.String(length=16), nullable=False),
        sa.Column("observed_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "compatibility IN ('compatible', 'incompatible')",
            name="ck_console_rule_load_negotiation_compatibility",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("certificate_principal"),
    )
    op.create_index(
        "ix_console_rule_load_negotiation_observed",
        "console_rule_load_observation_negotiation",
        ["observed_at"],
    )


def downgrade() -> None:
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM console_rule_load_observation_negotiation")
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade while protocol facts exist")
    op.drop_index(
        "ix_console_rule_load_negotiation_observed",
        table_name="console_rule_load_observation_negotiation",
    )
    op.drop_table("console_rule_load_observation_negotiation")
