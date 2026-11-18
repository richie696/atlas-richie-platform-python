# atlas-richie-persistence-core

Persistence contracts: unit of work, engine lifecycle and a migration SPI.
**Zero runtime dependencies** — no ORM, no driver.

Extracted because 13 stores in `sentinel-console` each hand-roll
`async_sessionmaker(engine, expire_on_commit=False)` and their own transaction
handling. These contracts let a component depend on persistence *semantics*
without depending on SQLAlchemy; the adapter is
`atlas-richie-persistence-sqlalchemy`.

## Contracts

```python
class Persistence(Protocol):
    def unit_of_work(self) -> AbstractAsyncContextManager[Any]: ...
    async def dispose(self) -> None: ...

class MigrationRunner(Protocol):
    async def upgrade(self, revision: str = "head") -> None: ...
    async def current_revision(self) -> str | None: ...
```

`unit_of_work()` yields a session handle inside a transaction: commit on clean
exit, rollback when the block raises. The handle type is adapter-specific.

`PersistenceError` is the base error type.

## Deliberately not included

A generic `Repository` abstraction, query builders, and MyBatis-style
mappers/interceptors. A generic repository is too vague to constrain anything
useful, and mappers/interceptors are JVM-specific. Callers use the session handle
directly.

Outbox support is a follow-up: it is needed by vector projection and already exists
inside the console, but it should be extracted against a real consumer rather than
speculatively.
