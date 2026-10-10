"""Run migrations only through an explicitly supplied, already validated connection."""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from atlas_richie.sentinel_console.infrastructure.persistence.base import ConsoleBase
from atlas_richie.sentinel_console.infrastructure.persistence import models as _models

_ = _models
config = context.config
target_metadata = ConsoleBase.metadata


def run_migrations(connection: Connection) -> None:
    """Apply revisions using the caller-owned connection and transaction."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is None:
    raise RuntimeError(
        "Console migrations require an explicit validated connection; "
        "do not configure a DSN in alembic.ini."
    )
run_migrations(connection)
