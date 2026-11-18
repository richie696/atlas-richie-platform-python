# atlas-richie-statemachine-redis

Redis-backed `StateStorage` and `SequenceAllocator` for `atlas-richie-statemachine-core`,
ported from the Java `RedisStateStorage` and `StateMachineKeyBuilder` key layout.

The core stays zero-dependency with an in-memory reference store; this adapter adds
durability and cross-instance sharing. Depends on `redis` and `statemachine-core` only.

## Usage

```python
import redis
from atlas_richie.statemachine_core import StateMachineEngine, StateMachineModel
from atlas_richie.statemachine_redis import RedisSequenceAllocator, RedisStateStorage

client = redis.Redis.from_url("redis://localhost:6379/0")
engine = StateMachineEngine(
    {"order": model},
    storage=RedisStateStorage(client),
    sequence_allocator=RedisSequenceAllocator(client),
)
```

## Key layout (Java-compatible)

```
{prefix}:state:{machine}:{businessId}          current state — never expires
{prefix}:history:list:{machine}:{businessId}   history — TTL + length cap
{prefix}:seq:{machine}:{businessId}            monotonic sequence (INCR)
```

Default prefix `platform:statemachine`. Current state deliberately has no expiry: a
state machine must not forget its state. History TTL defaults to 7 days and is
**forced to 7 days if a non-positive value is configured**, matching Java.

## Deliberate improvements over Java

- **Atomic history append.** Java reads the whole history JSON array, appends in
  memory and writes it back — concurrent transitions on the same business id can
  drop each other's entries. This uses a Redis LIST with `RPUSH`, so appends are
  atomic and no update is lost.
- **Bounded history.** `LTRIM` keeps the newest `max_history` entries (default 1000)
  in addition to the TTL, so a long-lived business object cannot grow the list
  without bound.
- **`create_time` is persisted** as epoch milliseconds. Java nulls it out on every
  read and write; keeping it makes the history actually useful for auditing.
- **`delete_state` also clears the sequence key**, so a reused business id starts
  from 1 rather than inheriting a stale counter.

History is returned newest-first, as in Java.

## Not ported

`AsyncThreadStorageManager` (817 lines), `StateSyncStreamConsumer` (404),
`StateCleanupScheduler` (220), `StateDbPersistenceService` (173) and the YAML config
loader. Relational persistence would need a platform persistence component, which
does not exist yet — `sentinel-console`'s SQLAlchemy layer is app-local by decision.

## Tests

Run against a real Redis and **skip cleanly** when none is reachable. Point
`ATLAS_RICHIE_STATEMACHINE_REDIS_URL` at your instance.
