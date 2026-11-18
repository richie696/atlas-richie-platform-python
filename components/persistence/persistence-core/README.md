# atlas-richie-persistence-core

Persistence contracts: unit of work, engine lifecycle and a migration SPI.
**Zero runtime dependencies** — no ORM, no driver.

Extracted because 13 stores in `sentinel-console` each hand-roll
`async_sessionmaker(engine, expire_on_commit=False)` and their own transaction
handling. These contracts let a component depend on persistence *semantics*
without depending on SQLAlchemy; the adapter is
`atlas-richie-persistence-sqlalchemy`.

`sentinel-console` deliberately stays on its own session handling (decided
2026-11-18): it is an *application*, and per `ARCHITECTURE.md` applications own
lifecycle and dependency assembly — wiring it into the component layer would tie
the console to the platform's release cadence. These contracts exist for
components that need persistence semantics without the SQLAlchemy dependency.

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

## Audit fields

The five audit/soft-delete fields (`createId` / `updateId` / `createTime` /
`updateTime` / `deleted`) are described here as a **policy**, not as an
interceptor — there are no ORM models in this workspace yet, so an entity handler
would be dead code.

```python
from atlas_richie.persistence_core import (
    AuditFieldPolicy,
    resolve_insert_values,
    resolve_update_values,
)

policy = AuditFieldPolicy()
# insert: fill the five fields, but only where the current value is None
values = resolve_insert_values(policy, current, username="alice", now=utc_now())
# update: refresh updateId / updateTime
values = resolve_update_values(policy, values, username="alice", now=utc_now())
```

Two documented differences from Java `DefaultFieldHandler`:

- **update refreshes instead of only filling blanks.** Java's `strictUpdateFill`
  keeps the insert-time `updateTime` unless the entity sets it; here
  `updateId` / `updateTime` are refreshed on every update, because an audit
  field should reflect the latest change.
- **the current user is injected by the caller.** Java reads it from
  `LoginUserContextHolder`; this workspace has no equivalent login context, so
  the adapter takes a provider and records an empty string when it yields nothing.

## Deliberately not included

A generic `Repository` abstraction, query builders, and MyBatis-style
mappers/interceptors. A generic repository is too vague to constrain anything
useful, and mappers/interceptors are JVM-specific. Callers use the session handle
directly.

Transactional outbox lives in `atlas-richie-persistence-sqlalchemy` (it needs a
driver), and is consumed by the vector projection chain.
