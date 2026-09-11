# R-M5.2 Design: L1 (cachetools) + stampede-prevention integration

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DESIGN** — implementation pending R-M5.1 worker
completion + this design's review.
**Companion:** R-M4 stampede prevention
(`docs/acceptance/R-M4-stampede-prevention-handoff.md`) is done.
R-M5.1 adds `loader_timeout_millis` to the 10 `*_with_lock` methods.
R-M5.2 (this doc) addresses the **L1-layer gap** that M4 didn't
cover.

## Problem

M4 added stampede prevention at the **manager layer**:
`RedisStringManager.get_with_lock` (and the 9 other `*_with_lock`
methods) acquire a per-key Lua stampede lock on the L2 (Redis)
side, so concurrent misses from **different processes** funnel to
ONE db_loader call per stampede.

What M4 does NOT cover:

- **In-process concurrent misses**. 10 threads in the same Python
  process call `RedisStringManager.get_with_lock("user:42", ...)`
  simultaneously. Each thread independently goes through:
  1. L1 (cachetools) check → miss
  2. Stampede lock acquire (only 1 wins) → 9 lose
  3. The 9 losers poll the L2 cache for the published value
  The 9 losers each do a 50ms-cadence L1 read. If the winner
  publishes, they get the value. If the winner times out, they
  see `None`.

  The L1 layer does not contribute to stampede prevention at all
  — M4's stampede lock IS the in-process funnel, *via the lock-loss
  polling path*. 9 threads × 50ms polls = 9 × N Redis `GET` round-
  trips during the wait. This is **acceptable** but not optimal.

- **L2DistributedCache.get() is a different path entirely.** The
  `L2DistributedCache` facade is a thin wrapper that does L1 → L2 →
  return; it has NO `db_loader` concept. The current call pattern
  is:

  ```python
  value = l2.get(key)
  if value is None:
      value = loader()       # caller owns this
      l2.set(key, value)     # caller owns this too
  ```

  10 threads calling `l2.get(key)` in parallel → 10 `loader()`
  invocations. There is **zero** stampede protection on this
  path. This is the gap M5.2 fills.

## Goal

Provide a `L2DistributedCache.get_or_load(key, loader, ...)` API
that combines:

- L1 short-circuit (cachetools hit → return, no network, no lock)
- In-process stampede prevention (per-key `threading.Lock` so
  concurrent in-process misses funnel to ONE loader call)
- L2 read-through (try Redis if L1 missed, populate L1 on hit)
- Optional `loader_timeout_millis` (reuse the M5.1 helper)
- LRU leak prevention for the per-key lock table

`L2DistributedCache.get()` (the old method) stays **unchanged** —
it's the no-loader cache facade and remains the right choice for
callers that don't want a loader-driven read. The new
`get_or_load` is purely additive.

## Design

### Public API

```python
def get_or_load(
    self,
    key: str,
    loader: Callable[[], bytes | None],
    *,
    ttl_seconds: int | None = None,        # default = instance TTL
    loader_timeout_millis: int | None = None,  # M5.1-style backstop
) -> bytes | None:
```

Returns the cached or freshly-loaded bytes (or `None` if loader
returned `None` or timed out).

### Internal flow

```
1. L1 check: cachetools.get(self._region, key) → hit? return
2. Acquire per-key in-process lock (threading.Lock, with LRU-bounded
   table; see "Lock-table leak prevention" below)
3. Double-check L1: cachetools.get → hit? release lock; return
4. L2 check: value_ops.get(key, bytes) → hit? L1.put + release lock; return
5. Loader call: _call_db_loader_with_timeout(loader, loader_timeout_millis)
   → None? release lock; return None
6. Write to BOTH L1 and L2 with the effective TTL
7. Release lock; return value
```

### Why per-key `threading.Lock` (not a single `Lock`)

A single `Lock` would serialize ALL `get_or_load` calls in the
process — wrong, because different keys are independent. A
`threading.Lock` **per key** gives the right granularity: concurrent
caller funnels are per-key, and a slow `loader("user:42")` doesn't
block `get_or_load("user:99", ...)`.

### Lock-table leak prevention

A naive `Dict[str, threading.Lock]` grows unboundedly in a long-
running process. We bound it two ways:

1. **LRU eviction** (the most-recently-used N keys' locks are
   retained; older ones are dropped). When evicted, a reference
   count or finalizer ensures we don't drop a lock a thread still
   holds. (Tricky; see alternative below.)
2. **Lock-per-key with `weakref`** (the lock object is held by the
   caller's frame, not the table; the table holds a `weakref` to
   it. When the last caller releases, the lock is GC'd and the
   weakref disappears). This is the cleanest, but `threading.Lock`
   doesn't support `weakref` directly — we wrap it in a small
   class.

The recommended approach is **option 2** (weakref-wrapped lock):

```python
class _KeyLock:
    """Wraps a `threading.Lock` so it can be held via `weakref`.

    The `L2DistributedCache._key_locks` table holds `weakref.ref`
    to instances of this class. When the last caller releases
    the lock and drops its reference, the instance is GC'd and
    the table's `weakref` becomes dead — a periodic sweep removes
    the dead entries.
    """

    __slots__ = ("_lock", "__weakref__")

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, *exc) -> None:
        self._lock.release()


class L2DistributedCache:
    def __init__(self, ...):
        # ...
        self._key_locks: weakref.WeakValueDictionary = (
            weakref.WeakValueDictionary()
        )
        self._key_locks_lock = threading.Lock()

    def _get_key_lock(self, key: str) -> _KeyLock:
        with self._key_locks_lock:
            lock = self._key_locks.get(key)
            if lock is None:
                lock = _KeyLock()
                self._key_locks[key] = lock
            return lock
```

`weakref.WeakValueDictionary` automatically drops entries when the
value is GC'd. The `_KeyLock` instance is held only by the
caller's stack frame during the `with` block; once the `with`
exits, the lock is released and (if no other thread is waiting)
GC'd.

`weakref` is not allowed on built-in `threading.Lock` directly;
the `_KeyLock` wrapper has `__weakref__` in its `__slots__` to
make it work.

### Why not use the Redis stampede lock here too?

The Redis stampede lock (M4) and the in-process lock (M5.2) are
**complementary**, not redundant:

- **M4's Redis lock** prevents multiple PROCESSES from each
  calling their own loader. It's the cross-process funnel.
- **M5.2's in-process lock** prevents multiple THREADS in the
  same process from each calling their own loader. It's the
  in-process funnel.

If we add BOTH, the cost is: 1 in-process lock acquire + 1
in-process lock release + 1 Redis `EVAL SET NX PX` + 1 Redis
`EVAL GET+DEL`. The in-process lock short-circuits the Redis
lock in the common case (winner of the in-process race also
wins the Redis race; losers of the in-process race never even
hit Redis).

**Decision (M5.2 final)**: We do **NOT** also acquire the Redis
stampede lock from `get_or_load`. The in-process lock is the
stampede defense at the L2 layer. The caller who wants
cross-process stampede defense should use
`RedisStringManager.get_with_lock` directly (which goes through
the Redis lock). Using `L2DistributedCache.get_or_load` is the
choice for "I want L1 + L2 caching and process-local stampede
defense, but I'm OK with the cross-process duplication if other
processes also miss".

This split is intentional and matches the Java side:
`L2DistributedCache` in Java does NOT take a stampede lock
either; only the `*Function.getFromXxxWithLock` API does.

### Re-use of the M5.1 helper

`_call_db_loader_with_timeout(loader, loader_timeout_millis)` is
already a module-level function in
`managers/redis_string_manager.py`. `L2DistributedCache.get_or_load`
imports and uses it directly.

### Compatibility with the existing L2 surface

- `L2DistributedCache.get(key)` — unchanged. No loader, no lock.
- `L2DistributedCache.set(key, value, ttl_seconds)` — unchanged.
- `L2DistributedCache.delete(key)` — unchanged.
- `L2DistributedCache.invalidate_l1(key)` — unchanged.
- `L2DistributedCache.stats()` — unchanged. We MAY add
  `in_process_loader_fan_in` counter for observability (counts
  how many times the in-process lock was lost by a waiter who
  then found the L1 already populated by the winner). Optional.

## Tests

Create `test_l2_distributed_cache_get_or_load.py` modeled on the
M4 test patterns. Cover:

1. **L1 hit short-circuits** — pre-populate L1, loader not called,
   no lock acquired.
2. **L1 miss + L2 hit** — loader not called, L1 populated, returns
   L2 value.
3. **L1 miss + L2 miss + loader succeeds** — loader called once,
   both L1 and L2 written, returns loader value.
4. **L1 miss + L2 miss + loader returns `None`** — no writes,
   returns `None`.
5. **L1 miss + L2 miss + loader exceeds timeout** — returns
   `None`, no writes, no exception.
6. **L1 miss + L2 miss + loader raises** — exception propagates,
   no writes, lock released cleanly.
7. **10 threads concurrent** — loader called exactly once
   (in-process funnel), all 10 threads return the same value.
8. **Concurrent loaders for DIFFERENT keys** — 10 threads, 5 keys
   (2 each), each key's loader called once → 5 loader invocations
   total.
9. **`loader_timeout_millis=None`** — legacy unbounded behavior.
10. **`loader_timeout_millis=0` / negative** — `ValueError`.
11. **Per-key lock table shrinks** — after all `with` blocks exit,
    the `_key_locks` table has zero (or near-zero) live entries
    (verify via `weakref` introspection).
12. **L1 TTL applied** — value expires from L1 after the expected
    window.

## Files to change

| File | Change |
|---|---|
| `local/l2_distributed_cache.py` | Add `_KeyLock` class; add `_key_locks` WeakValueDictionary; add `get_or_load` method. |
| `tests/test_l2_distributed_cache_get_or_load.py` | NEW — 12 tests as above |

## Files NOT to change

- `managers/redis_string_manager.py` (the M5.1 sample is final; we
  re-use `_call_db_loader_with_timeout` but don't modify it)
- `managers/redis_field_manager.py`,
  `managers/redis_collection_manager.py`,
  `managers/redis_struct_manager.py` (M5.1 worker handles those)
- `local/l2_cache_factory.py` (the factory returns `L2DistributedCache`
  instances; no change needed)
- `local/local_cache_manager.py` and the `cachetools` integration
  (the L1 layer is a passive cache; we don't need to teach it about
  stampede)

## Open questions for owner

1. **Should `get_or_load` ALSO acquire the Redis stampede lock?**
   The design above says "no, only the in-process lock". The
   alternative is "yes, both" — full stampede defense at the cost
   of one extra Redis round-trip per call. Owner should choose
   based on whether cross-process loader duplication is acceptable.

2. **Should the L1 layer's eviction be aware of in-flight loads?**
   Right now if thread A is in `get_or_load`'s loader call and
   thread B's `l1.put` evicts thread A's key from L1, thread A
   still completes and writes L1. This is fine; cachetools handles
   it. But should we hold a "reserved" slot to prevent premature
   eviction? (Cachetools doesn't have this concept; this is a
   custom-cache design choice. **Decision needed**: no, just rely
   on cachetools LRU.)

3. **Should `get_or_load` support batch keys (like
   `RedisFieldManager.get_many_with_lock`)?** Out of scope for
   M5.2 (which is single-key only). Batch-at-L2 would need a
   new `L2DistributedCache.get_or_load_many` method. Defer to
   M5.3 if needed.

4. **Should we expose `get_or_load` as a method on
   `RedisProviderRegistrar` (or `GlobalCache`)?** Probably not
   for M5.2 — `L2DistributedCache` is the right entry point.
   `L2CacheFactory` is the constructor. Keep the surface small.

## Validation

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python
source .venv/bin/activate

# New tests
python -m pytest components/cache/cache-redis/tests/test_l2_distributed_cache_get_or_load.py -v
# → 12 passed

# Full suite (1 pre-existing flaky keyspace test is known)
python -m pytest components/cache/cache-core/tests/ components/cache/cache-redis/tests/ -q
# → 471 + 10 (M5.1 sample) + 50 (M5.1 worker) + 12 (M5.2) - 1 (flaky)
#    = ~542 passed, 1 failed (flaky), 4 skipped, 0 NEW failures
```

## Trade-offs and what we learned

### Why per-key `threading.Lock` and not `asyncio.Lock` / `contextvars`

`L2DistributedCache` is a synchronous cache facade; its `get` /
`set` are sync. `get_or_load` is sync too — the `loader` callable
is sync. `asyncio.Lock` doesn't apply to a sync path. `contextvars`
solve the wrong problem (context isolation across async tasks, not
thread serialization). Plain `threading.Lock` is the right tool.

### Why `WeakValueDictionary` and not a manually-managed LRU

`cachetools.LRUCache` doesn't support `weakref` directly (the
values are stored as strong refs to support the LRU eviction
order). We could compose `LRUCache` + `WeakValueDictionary` but
the complexity isn't worth it. `WeakValueDictionary` is
sufficient: locks are tiny (a `threading.Lock` is ~100 bytes
including the OS mutex), and the worst case in a long-running
process is "a few thousand locks still alive because some
thread is mid-`with`", which is bounded by the number of
concurrent threads in flight (typically << 1000).

If a process is genuinely concerned about lock-table memory in
the long tail, we can add a periodic `_key_locks.sweep()` call
(manual GC for `WeakValueDictionary` is also possible via
`gc.collect()` per N calls). Defer until measurement.

### Why we DON'T re-use `_stampede_acquire` / `_stampede_release`

The Redis stampede lock and the in-process lock have different
semantics, lifetimes, and key namespaces. Trying to unify them
behind one Lua script or one `_KeyLock` abstraction would couple
two layers that should stay independent (the cross-process
funnel and the in-process funnel are different infrastructure).

`_call_db_loader_with_timeout` IS the right level of sharing —
it's a thread-pool concern, orthogonal to lock concerns.

## Follow-ups (post-M5.2)

1. **M5.3 (optional) — L2 `get_or_load_many`**. Batch loader support.
2. **L1 singleflight for callers using the OLD `get` + own loader
   path.** Not a framework concern; document as "use `get_or_load`
   instead of `get` if you have a loader".
3. **Stats observability.** `in_process_loader_fan_in`,
   `in_process_loader_wait_seconds`, `key_lock_table_size`.
4. **Stampede lock + negative cache (M5 candidate).** When loader
   times out, write a short-TTL `None` entry so the next caller
   doesn't immediately retry. Defers to M5.4 or later.
