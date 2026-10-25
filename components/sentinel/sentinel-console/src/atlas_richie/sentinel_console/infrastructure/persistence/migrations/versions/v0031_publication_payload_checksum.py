"""Persist the exact encoded configuration payload checksum per publication."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_publication_payload_checksum"
down_revision = "0030_publication_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an internal digest domain without changing Console API fields."""
    op.add_column(
        "console_rule_publication",
        sa.Column("target_payload_checksum", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    """Refuse to discard accepted payload digests after they are recorded."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_publication "
            "WHERE target_payload_checksum IS NOT NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade while publication payload checksums are recorded"
        )
    op.drop_column("console_rule_publication", "target_payload_checksum")
