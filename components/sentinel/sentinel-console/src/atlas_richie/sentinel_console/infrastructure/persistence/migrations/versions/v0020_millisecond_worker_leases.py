"""Preserve millisecond lease boundaries on MySQL."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0020_millisecond_worker_leases"
down_revision = "0019_rule_binding_registration"
branch_labels = None
depends_on = None

_LEASE_COLUMNS = (
    ("console_rule_operation", "work_lease_expires_at"),
    ("console_rule_activation_plan", "claim_lease_expires_at"),
)


def upgrade() -> None:
    """Give MySQL worker leases the millisecond precision used by the ports."""
    if op.get_bind().dialect.name != "mysql":
        return
    for table_name, column_name in _LEASE_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.DATETIME(),
            type_=mysql.DATETIME(fsp=3),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Avoid dropping subsecond precision while either worker owns a lease."""
    if op.get_bind().dialect.name != "mysql":
        return
    active_claims = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT "
                "(SELECT count(*) FROM console_rule_operation "
                "WHERE work_claim_token IS NOT NULL) + "
                "(SELECT count(*) FROM console_rule_activation_plan "
                "WHERE claim_token IS NOT NULL)"
            )
        )
        .scalar_one()
    )
    if active_claims:
        raise RuntimeError(
            "cannot remove millisecond precision while worker claims are active"
        )
    for table_name, column_name in _LEASE_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.DATETIME(fsp=3),
            type_=mysql.DATETIME(),
            existing_nullable=True,
        )
