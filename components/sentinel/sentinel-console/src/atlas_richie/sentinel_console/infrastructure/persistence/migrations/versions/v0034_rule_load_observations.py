"""Persist authenticated rule-load observations and projection delivery."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

revision = "0034_rule_load_observations"
down_revision = "0033_rule_catalog_projection"
branch_labels = None
depends_on = None

_MILLISECOND_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=3), "mysql"
)
_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=6), "mysql"
)


def upgrade() -> None:
    """Add append-only inbox, scoped sequence, durable outbox and current view."""
    op.create_table(
        "console_rule_load_observation_sequence",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "last_sequence >= 0", name="ck_console_rule_load_observation_sequence"
        ),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["console_rule_binding.binding_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("certificate_principal", "process_epoch", "binding_id"),
    )
    op.create_table(
        "console_rule_load_observation_inbox",
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("process_id", sa.String(length=200), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("profile_id", sa.String(length=200), nullable=False),
        sa.Column("event_kind", sa.String(length=24), nullable=False),
        sa.Column("active_snapshot", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.JSON(), nullable=True),
        sa.Column("observed_at", _MILLISECOND_TIMESTAMP, nullable=False),
        sa.Column("received_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["console_rule_binding.binding_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "certificate_principal",
            "process_epoch",
            "binding_id",
            "sequence",
            name="uq_console_rule_load_observation_sequence",
        ),
    )
    op.create_index(
        "ix_console_rule_load_observation_binding_received",
        "console_rule_load_observation_inbox",
        ["binding_id", "received_at"],
    )
    op.create_index(
        "ix_console_rule_load_observation_process_received",
        "console_rule_load_observation_inbox",
        ["certificate_principal", "process_epoch", "received_at"],
    )
    op.create_table(
        "console_rule_load_observation_outbox",
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("available_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", _PRECISE_TIMESTAMP, nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'delivered', 'parked')",
            name="ck_console_rule_load_observation_outbox_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_console_rule_load_observation_outbox_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["console_rule_load_observation_inbox.observation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("observation_id"),
    )
    op.create_index(
        "ix_console_rule_load_observation_outbox_claim",
        "console_rule_load_observation_outbox",
        ["state", "available_at", "lease_until"],
    )
    op.create_table(
        "console_rule_load_observation_current",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("observation_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("process_id", sa.String(length=200), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.String(length=200), nullable=False),
        sa.Column("event_kind", sa.String(length=24), nullable=False),
        sa.Column("active_snapshot", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.JSON(), nullable=True),
        sa.Column("observed_at", _MILLISECOND_TIMESTAMP, nullable=False),
        sa.Column("received_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["console_rule_binding.binding_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["console_rule_load_observation_inbox.observation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("certificate_principal", "binding_id"),
    )
    op.create_index(
        "ix_console_rule_load_observation_current_scope",
        "console_rule_load_observation_current",
        ["environment_id", "app_id", "binding_id"],
    )


def downgrade() -> None:
    """Preserve accepted runtime history rather than silently dropping it."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_load_observation_inbox")
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade while rule-load observations exist")
    op.drop_index(
        "ix_console_rule_load_observation_current_scope",
        table_name="console_rule_load_observation_current",
    )
    op.drop_table("console_rule_load_observation_current")
    op.drop_index(
        "ix_console_rule_load_observation_outbox_claim",
        table_name="console_rule_load_observation_outbox",
    )
    op.drop_table("console_rule_load_observation_outbox")
    op.drop_index(
        "ix_console_rule_load_observation_process_received",
        table_name="console_rule_load_observation_inbox",
    )
    op.drop_index(
        "ix_console_rule_load_observation_binding_received",
        table_name="console_rule_load_observation_inbox",
    )
    op.drop_table("console_rule_load_observation_inbox")
    op.drop_table("console_rule_load_observation_sequence")
