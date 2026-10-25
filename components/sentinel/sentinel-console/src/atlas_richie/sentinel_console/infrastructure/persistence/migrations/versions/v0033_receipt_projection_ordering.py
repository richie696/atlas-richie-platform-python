"""Store V1 receipt identity and sequence beside its API-neutral projection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_receipt_projection_ordering"
down_revision = "0032_publication_receipt_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add internal idempotency/order metadata without changing Console DTOs."""
    op.add_column(
        "console_rule_publication_receipt",
        sa.Column("receipt_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "console_rule_publication_receipt",
        sa.Column("receipt_sequence", sa.BigInteger(), nullable=True),
    )
    with op.batch_alter_table("console_rule_publication_receipt") as batch:
        batch.create_check_constraint(
            "ck_console_rule_publication_receipt_ordering",
            "(receipt_id IS NULL AND receipt_sequence IS NULL) OR "
            "(receipt_id IS NOT NULL AND receipt_sequence IS NOT NULL AND receipt_sequence > 0)",
        )
        batch.create_unique_constraint(
            "uq_console_rule_publication_receipt_id", ["receipt_id"]
        )


def downgrade() -> None:
    """Retain accepted inbox facts; metadata columns can be removed only if unused."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text(
            "SELECT count(*) FROM console_rule_publication_receipt "
            "WHERE receipt_id IS NOT NULL"
        )
    ).scalar_one()
    if count:
        raise RuntimeError("cannot downgrade while receipt projections exist")
    with op.batch_alter_table("console_rule_publication_receipt") as batch:
        batch.drop_constraint("uq_console_rule_publication_receipt_id", type_="unique")
        batch.drop_constraint(
            "ck_console_rule_publication_receipt_ordering", type_="check"
        )
        batch.drop_column("receipt_sequence")
        batch.drop_column("receipt_id")
