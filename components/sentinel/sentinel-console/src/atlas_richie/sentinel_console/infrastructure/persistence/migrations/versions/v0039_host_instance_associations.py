"""Persist explicit HOST-to-worker associations independently of metrics."""

import sqlalchemy as sa
from alembic import op

revision = "0039_host_instance_associations"
down_revision = "0038_monitoring_source_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "console_host_instance_association",
        sa.Column("environment_id", sa.String(length=200), nullable=False),
        sa.Column("app_id", sa.String(length=200), nullable=False),
        sa.Column("instance_id", sa.String(length=200), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("host_id", sa.String(length=512), nullable=False),
        sa.Column("revision", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(environment_id) BETWEEN 1 AND 200 AND "
            "length(app_id) BETWEEN 1 AND 200 AND "
            "length(instance_id) BETWEEN 1 AND 200 AND "
            "length(source_id) BETWEEN 1 AND 200 AND "
            "length(host_id) BETWEEN 1 AND 512",
            name="ck_console_host_association_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["console_monitoring_source.source_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("environment_id", "app_id", "instance_id"),
    )
    op.create_index(
        "ix_console_host_association_source",
        "console_host_instance_association",
        ["environment_id", "source_id"],
    )
    op.create_table(
        "console_host_association_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=False),
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'completed'", name="ck_console_host_association_operation_status"
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["console_account.account_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("operation_id"),
    )
    op.create_index(
        "ix_console_host_association_operation_actor",
        "console_host_association_operation",
        ["actor_account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_console_host_association_operation_actor",
        table_name="console_host_association_operation",
    )
    op.drop_table("console_host_association_operation")
    op.drop_index(
        "ix_console_host_association_source",
        table_name="console_host_instance_association",
    )
    op.drop_table("console_host_instance_association")
