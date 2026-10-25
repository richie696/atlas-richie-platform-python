"""Persist authenticated managed-publication receipts and Collector outbox."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME as MySQLDateTime

revision = "0032_publication_receipt_outbox"
down_revision = "0031_publication_payload_checksum"
branch_labels = None
depends_on = None

_MILLISECOND_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=3), "mysql"
)
_PRECISE_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    MySQLDateTime(fsp=6), "mysql"
)


def upgrade() -> None:
    """Create independent receipt ordering, immutable inbox, and durable outbox."""
    op.create_table(
        "console_rule_publication_receipt_sequence",
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("last_sequence >= 0", name="ck_console_receipt_sequence"),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("certificate_principal", "process_epoch"),
    )
    op.create_table(
        "console_rule_publication_receipt_inbox",
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("certificate_principal", sa.String(length=255), nullable=False),
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("process_id", sa.String(length=200), nullable=False),
        sa.Column("process_epoch", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("publication_id", sa.String(length=200), nullable=False),
        sa.Column("target_version_id", sa.String(length=200), nullable=False),
        sa.Column("target_payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("source_revision", sa.String(length=200), nullable=True),
        sa.Column("observed_at", _MILLISECOND_TIMESTAMP, nullable=False),
        sa.Column("received_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("body_sha256", sa.String(length=64), nullable=False),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["certificate_principal"],
            ["console_metrics_reporter_binding.certificate_principal"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
        sa.UniqueConstraint(
            "certificate_principal",
            "process_epoch",
            "sequence",
            name="uq_console_receipt_principal_epoch_sequence",
        ),
    )
    op.create_index(
        "ix_console_receipt_inbox_received",
        "console_rule_publication_receipt_inbox",
        ["received_at", "receipt_id"],
    )
    op.create_table(
        "console_rule_publication_receipt_outbox",
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("available_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", _PRECISE_TIMESTAMP, nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("rejection_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", _PRECISE_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'delivered', 'parked')",
            name="ck_console_receipt_outbox_state",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_console_receipt_outbox_attempts"
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["console_rule_publication_receipt_inbox.receipt_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("receipt_id"),
    )
    op.create_index(
        "ix_console_receipt_outbox_claim",
        "console_rule_publication_receipt_outbox",
        ["state", "available_at", "lease_until"],
    )


def downgrade() -> None:
    """Refuse to erase authenticated receipt history during downgrade."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_publication_receipt_inbox")
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade while publication receipts exist")
    op.drop_index(
        "ix_console_receipt_outbox_claim",
        table_name="console_rule_publication_receipt_outbox",
    )
    op.drop_table("console_rule_publication_receipt_outbox")
    op.drop_index(
        "ix_console_receipt_inbox_received",
        table_name="console_rule_publication_receipt_inbox",
    )
    op.drop_table("console_rule_publication_receipt_inbox")
    op.drop_table("console_rule_publication_receipt_sequence")
