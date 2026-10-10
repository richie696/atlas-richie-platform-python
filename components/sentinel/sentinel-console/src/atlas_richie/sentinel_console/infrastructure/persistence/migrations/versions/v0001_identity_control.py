"""Initial Console identity, bootstrap-operation, and audit schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_identity_control"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the first relational control-plane schema."""
    op.create_table(
        "console_guard",
        sa.Column(
            "singleton_id", sa.SmallInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("initialized", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("singleton_id = 1", name="ck_console_guard_singleton"),
        sa.PrimaryKeyConstraint("singleton_id"),
    )
    op.create_table(
        "console_account",
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("username_key", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role_id", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role_id IN ('admin', 'view')", name="ck_console_account_role"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name="ck_console_account_status"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_console_account_revision"),
        sa.PrimaryKeyConstraint("account_id"),
        sa.UniqueConstraint("username_key", name="uq_console_account_username_key"),
    )
    op.create_index(
        "ix_console_account_status_role",
        "console_account",
        ["status", "role_id"],
    )
    op.create_table(
        "console_session",
        sa.Column("session_hash", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("session_epoch", sa.String(length=36), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["console_account.account_id"],
            name="fk_console_session_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("session_hash"),
    )
    op.create_index(
        "ix_console_session_account_expiry",
        "console_session",
        ["account_id", "expires_at"],
    )
    op.create_table(
        "console_initialization_operation",
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("operator_session_hash", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'rejected')",
            name="ck_console_initialization_status",
        ),
        sa.PrimaryKeyConstraint("request_key"),
        sa.UniqueConstraint("operation_id", name="uq_console_initialization_operation_id"),
    )
    op.create_index(
        "ix_console_initialization_operator",
        "console_initialization_operation",
        ["operator_session_hash"],
    )
    op.create_table(
        "console_audit_event",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("actor_account_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("target_kind", sa.String(length=48), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'completed', 'rejected')",
            name="ck_console_audit_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["console_account.account_id"],
            name="fk_console_audit_actor",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_console_audit_created_event",
        "console_audit_event",
        ["created_at", "event_id"],
    )
    op.create_index(
        "ix_console_audit_actor_created",
        "console_audit_event",
        ["actor_account_id", "created_at"],
    )
    op.bulk_insert(
        sa.table(
            "console_guard",
            sa.column("singleton_id", sa.SmallInteger()),
            sa.column("initialized", sa.Boolean()),
            sa.column("revision", sa.BigInteger()),
        ),
        [{"singleton_id": 1, "initialized": False, "revision": 0}],
    )


def downgrade() -> None:
    """Remove the schema in reverse dependency order."""
    op.drop_index("ix_console_audit_actor_created", table_name="console_audit_event")
    op.drop_index("ix_console_audit_created_event", table_name="console_audit_event")
    op.drop_table("console_audit_event")
    op.drop_index(
        "ix_console_initialization_operator",
        table_name="console_initialization_operation",
    )
    op.drop_table("console_initialization_operation")
    op.drop_index("ix_console_session_account_expiry", table_name="console_session")
    op.drop_table("console_session")
    op.drop_index("ix_console_account_status_role", table_name="console_account")
    op.drop_table("console_account")
    op.drop_table("console_guard")
