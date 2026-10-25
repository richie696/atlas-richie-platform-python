"""Preserve publication phase timestamps at the Console wire precision."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0022_millisecond_publication_times"
down_revision = "0021_rule_publication_receipts"
branch_labels = None
depends_on = None

_PUBLICATION_TIMESTAMP_COLUMNS = (
    "created_at",
    "validation_observed_at",
    "write_observed_at",
    "read_back_observed_at",
)


def upgrade() -> None:
    """Give MySQL the subsecond precision required by publication facts."""
    if op.get_bind().dialect.name != "mysql":
        return
    for column_name in _PUBLICATION_TIMESTAMP_COLUMNS:
        op.alter_column(
            "console_rule_publication",
            column_name,
            existing_type=mysql.DATETIME(),
            type_=mysql.DATETIME(fsp=3),
            existing_nullable=column_name != "created_at",
        )


def downgrade() -> None:
    """Refuse to discard subsecond publication evidence."""
    if op.get_bind().dialect.name != "mysql":
        return
    fractional_facts = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM console_rule_publication WHERE "
            "MICROSECOND(created_at) != 0 OR "
            "(validation_observed_at IS NOT NULL AND "
            "MICROSECOND(validation_observed_at) != 0) OR "
            "(write_observed_at IS NOT NULL AND "
            "MICROSECOND(write_observed_at) != 0) OR "
            "(read_back_observed_at IS NOT NULL AND "
            "MICROSECOND(read_back_observed_at) != 0)"
        )
    ).scalar_one()
    if fractional_facts:
        raise RuntimeError(
            "cannot remove millisecond precision while publication timestamps "
            "contain subsecond evidence"
        )
    for column_name in _PUBLICATION_TIMESTAMP_COLUMNS:
        op.alter_column(
            "console_rule_publication",
            column_name,
            existing_type=mysql.DATETIME(fsp=3),
            type_=mysql.DATETIME(),
            existing_nullable=column_name != "created_at",
        )
