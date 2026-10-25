"""Persist the independent source-publication phase observations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_rule_publications"
down_revision = "0009_rule_activation_plans"
branch_labels = None
depends_on = None

_STATES = "'awaiting', 'running', 'succeeded', 'failed', 'unknown'"
_REASONS = (
    "'conflict', 'unavailable', 'rejected', 'readback_mismatch', "
    "'unsupported', 'unknown'"
)


def upgrade() -> None:
    """Create publication history without coupling it to provider execution."""
    op.create_table(
        "console_rule_publication",
        sa.Column("publication_id", sa.String(length=200), nullable=False),
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("target_version_id", sa.String(length=200), nullable=False),
        sa.Column("target_checksum", sa.String(length=200), nullable=False),
        sa.Column("base_version_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validation_state", sa.String(length=16), nullable=False),
        sa.Column("validation_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_reason", sa.String(length=32), nullable=True),
        sa.Column("write_state", sa.String(length=16), nullable=False),
        sa.Column("write_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("write_reason", sa.String(length=32), nullable=True),
        sa.Column("read_back_state", sa.String(length=16), nullable=False),
        sa.Column("read_back_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_back_reason", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            f"validation_state IN ({_STATES})",
            name="ck_console_rule_publication_validation_state",
        ),
        sa.CheckConstraint(
            f"write_state IN ({_STATES})",
            name="ck_console_rule_publication_write_state",
        ),
        sa.CheckConstraint(
            f"read_back_state IN ({_STATES})",
            name="ck_console_rule_publication_readback_state",
        ),
        sa.CheckConstraint(
            f"validation_reason IS NULL OR validation_reason IN ({_REASONS})",
            name="ck_console_rule_publication_validation_reason",
        ),
        sa.CheckConstraint(
            f"write_reason IS NULL OR write_reason IN ({_REASONS})",
            name="ck_console_rule_publication_write_reason",
        ),
        sa.CheckConstraint(
            f"read_back_reason IS NULL OR read_back_reason IN ({_REASONS})",
            name="ck_console_rule_publication_readback_reason",
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"], ["console_rule_version.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"], ["console_rule_version.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("publication_id"),
    )
    op.create_index(
        "ix_console_rule_publication_binding_created",
        "console_rule_publication",
        ["binding_id", "created_at", "publication_id"],
    )


def downgrade() -> None:
    """Refuse to erase publication facts once any exist."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_publication")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade 0010_rule_publications while publication history exists"
        )
    op.drop_index(
        "ix_console_rule_publication_binding_created",
        table_name="console_rule_publication",
    )
    op.drop_table("console_rule_publication")
