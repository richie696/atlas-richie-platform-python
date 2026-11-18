# atlas-richie-persistence-sqlalchemy

SQLAlchemy 2 async adapter for `atlas-richie-persistence-core`, plus an Alembic
migration runner.

## Usage

```python
from atlas_richie.persistence_sqlalchemy import SqlAlchemyPersistence

persistence = SqlAlchemyPersistence("postgresql+psycopg://user:pass@host/db")

async with persistence.unit_of_work() as session:
    session.add(Order(...))
    await session.flush()
    ...
# commits here; rolls back if the block raised

await persistence.dispose()
```

`expire_on_commit=False` is the default, so ORM instances stay usable after the
block — the assumption the console stores already make. Override via
`expire_on_commit=True`, and pass `engine_kwargs` / `session_kwargs` for pool and
session tuning. `persistence.engine` is an escape hatch for DDL.

For SQLite in-memory, pass `engine_kwargs={"poolclass": StaticPool}`; otherwise
each pooled connection gets its own private database.

## Migrations

```python
from atlas_richie.persistence_sqlalchemy import AlembicMigrationRunner

runner = AlembicMigrationRunner("path/to/migrations", "sqlite:///./app.db")
await runner.upgrade("head")
await runner.current_revision()
```

Alembic's command API is synchronous, so it runs in a worker thread. The migration
URL is a **sync** driver URL supplied explicitly — it is not derived from the async
URL, because rewriting `sqlite+aiosqlite://` to `sqlite://` is driver-specific
guesswork and a wrong guess would silently migrate a different database.

Alembic is an optional extra: `[migrations]`. Driver extras: `[sqlite]`,
`[postgres]`.

## Tests

Run against SQLite (file-backed via `tmp_path`, and in-memory with `StaticPool`),
so no external database is needed and the suite runs offline in CI. Tests drive
coroutines with `asyncio.run` rather than depending on pytest-asyncio, so they
behave identically under standalone and aggregate pytest runs.
