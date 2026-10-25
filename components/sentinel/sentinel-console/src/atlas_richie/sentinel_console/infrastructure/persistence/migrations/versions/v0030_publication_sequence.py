"""Persist a monotonic publication sequence per binding."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_publication_sequence"
down_revision = "0029_incident_event_negotiations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill stable sequence values before requiring them for new rows."""
    op.create_table(
        "console_rule_binding_publication_sequence",
        sa.Column("binding_id", sa.String(length=200), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("binding_id"),
    )
    op.add_column(
        "console_rule_publication",
        sa.Column("publication_sequence", sa.BigInteger(), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT binding_id, publication_id FROM console_rule_publication "
            "ORDER BY binding_id, created_at, publication_id"
        )
    ).mappings()
    counters: dict[str, int] = {}
    for row in rows:
        binding_id = row["binding_id"]
        sequence = counters.get(binding_id, 0) + 1
        counters[binding_id] = sequence
        connection.execute(
            sa.text(
                "UPDATE console_rule_publication SET publication_sequence = :sequence "
                "WHERE publication_id = :publication_id"
            ),
            {"sequence": sequence, "publication_id": row["publication_id"]},
        )

    for binding_id, sequence in counters.items():
        connection.execute(
            sa.text(
                "INSERT INTO console_rule_binding_publication_sequence "
                "(binding_id, last_sequence) VALUES (:binding_id, :sequence)"
            ),
            {"sequence": sequence, "binding_id": binding_id},
        )
    connection.execute(
        sa.text(
            "INSERT INTO console_rule_binding_publication_sequence "
            "(binding_id, last_sequence) "
            "SELECT binding_id, 0 FROM console_rule_binding "
            "WHERE binding_id NOT IN ("
            "SELECT binding_id FROM console_rule_binding_publication_sequence)"
        )
    )

    with op.batch_alter_table("console_rule_publication") as batch:
        batch.alter_column(
            "publication_sequence",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_console_rule_publication_binding_sequence",
            ["binding_id", "publication_sequence"],
        )


def downgrade() -> None:
    """Refuse to discard monotonic identities after publications exist."""
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT count(*) FROM console_rule_publication")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "cannot downgrade publication sequence while publication history exists"
        )
    with op.batch_alter_table("console_rule_publication") as batch:
        batch.drop_constraint(
            "uq_console_rule_publication_binding_sequence", type_="unique"
        )
        batch.drop_column("publication_sequence")
    op.drop_table("console_rule_binding_publication_sequence")
