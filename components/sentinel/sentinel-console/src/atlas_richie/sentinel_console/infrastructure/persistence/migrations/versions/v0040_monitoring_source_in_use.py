"""Allow durable monitoring-source receipts to record reference rejection."""

from alembic import op

revision = "0040_monitoring_source_in_use"
down_revision = "0039_host_instance_associations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the stable source_in_use operation outcome across SQL dialects."""
    with op.batch_alter_table("console_monitoring_source_operation") as batch_op:
        batch_op.drop_constraint(
            "ck_console_monitoring_source_operation_reason", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_console_monitoring_source_operation_reason",
            "reason IS NULL OR reason IN "
            "('conflict', 'not_found', 'check_required', 'check_mismatch', 'source_in_use')",
        )


def downgrade() -> None:
    """Retain the widened receipt contract once the new code may be persisted."""
    raise RuntimeError(
        "cannot remove source_in_use receipts after Console API 0.18.0 use"
    )
