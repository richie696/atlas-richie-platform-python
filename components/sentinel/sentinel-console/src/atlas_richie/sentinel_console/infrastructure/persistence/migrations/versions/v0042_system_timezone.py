"""Persist the Console-wide IANA timezone used for human-readable timestamps."""

from alembic import op
import sqlalchemy as sa

revision = "0042_system_timezone"
down_revision = "0041_account_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "console_system_settings",
        sa.Column("singleton_id", sa.SmallInteger(), primary_key=True),
        sa.Column("time_zone", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="1"),
        sa.CheckConstraint("singleton_id = 1", name="ck_console_system_settings_singleton"),
        sa.CheckConstraint("revision >= 1", name="ck_console_system_settings_revision"),
    )
    op.execute(
        sa.text(
            "INSERT INTO console_system_settings (singleton_id, time_zone, revision) "
            "VALUES (1, 'Asia/Shanghai', 1)"
        )
    )


def downgrade() -> None:
    op.drop_table("console_system_settings")
