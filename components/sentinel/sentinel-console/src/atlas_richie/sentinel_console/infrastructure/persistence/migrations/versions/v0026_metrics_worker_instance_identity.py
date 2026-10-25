"""Enforce one Metrics V2 Reporter per dashboard worker identity."""

import sqlalchemy as sa
from alembic import op

revision = "0026_metrics_worker_instance_identity"
down_revision = "0025_registered_source_deletion"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_console_metrics_reporter_worker_instance"


def upgrade() -> None:
    """Reject ambiguous worker identities before enforcing the frozen contract."""
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT environment_id, app_id, instance_id "
                "FROM console_metrics_reporter_binding "
                "GROUP BY environment_id, app_id, instance_id HAVING count(*) > 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Metrics V2 reporter data contains duplicate worker identities; "
            "resolve enrollment conflicts before applying 0026"
        )
    with op.batch_alter_table("console_metrics_reporter_binding") as batch_op:
        batch_op.create_unique_constraint(
            _CONSTRAINT, ["environment_id", "app_id", "instance_id"]
        )


def downgrade() -> None:
    """Remove only the worker-identity constraint, preserving reporter data."""
    with op.batch_alter_table("console_metrics_reporter_binding") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="unique")
