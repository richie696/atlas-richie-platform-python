"""Persist the latest instance-level outcome for each rule publication."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0021_rule_publication_receipts"
down_revision = "0020_millisecond_worker_leases"
branch_labels = None
depends_on = None

_MILLISECOND_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=3), "mysql"
)


def upgrade() -> None:
    """Create a binding-scoped latest-receipt projection, not a wire inbox."""
    op.create_table(
        "console_rule_publication_receipt",
        sa.Column("publication_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("process_epoch", sa.String(length=200), nullable=True),
        sa.Column("loaded_process_epoch", sa.String(length=200), nullable=True),
        sa.Column("target_version_id", sa.String(length=200), nullable=False),
        sa.Column("loaded_version_id", sa.String(length=200), nullable=True),
        sa.Column("loaded_checksum", sa.String(length=200), nullable=True),
        sa.Column("applied_at", _MILLISECOND_TIMESTAMP, nullable=True),
        sa.Column("last_report_at", _MILLISECOND_TIMESTAMP, nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "state IN ('applied', 'pending', 'failed', 'unknown', 'restart_required')",
            name="ck_console_rule_publication_receipt_state",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["console_rule_publication.publication_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("publication_id", "instance_id"),
    )

def downgrade() -> None:
    """Refuse to discard runtime application evidence."""
    count = op.get_bind().execute(
        sa.text("SELECT count(*) FROM console_rule_publication_receipt")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade 0021_rule_publication_receipts while receipts exist"
        )
    op.drop_table("console_rule_publication_receipt")
