# R-M5.1 Handoff: `loader_timeout_millis` for all 10 `*_with_lock` methods

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — 10 `*_with_lock` methods across 4 manager
classes now accept an optional `loader_timeout_millis` keyword
argument that bounds `db_loader` execution. **98 new tests** (10
sample + 56 Field + 32 Collection+Struct) all passing; full suite
**560 passed, 4 skipped, 0 new failures**.

## Motivation

R-M4 stampede prevention guards against **loader fan-out** (10
concurrent misses funnel to 1 loader call) but does not bound
**loader latency** itself. A misbehaving `db_loader` (network
hang, slow downstream, leaked FD) can hold the Redis stampede
lock for the full `timeout_millis` TTL, blocking all waiters.

R-M5.1 closes this gap. The caller can now pass
`loader_timeout_millis=N` and a hung loader will be cut off at
`N` milliseconds; the method returns `None` (no cache write, no
exception) and releases the stampede lock so other waiters can
re-acquire and (if they have a better `db_loader` to try) make
progress.

## The new parameter

```python
def get_with_lock(
    self,
    key: str,
    timeout_millis: int,
    db_loader: Callable[[], str | None],
    *,
    loader_timeout_millis: int | None = None,  # NEW (M5.1)
) -> str | None:
```

- `None` (default) = legacy behavior — no loader timeout, block
  forever. **100% backward compatible**; existing callers see no
  change.
- `> 0` = `db_loader` runs in a single-worker
  `ThreadPoolExecutor`; if it doesn't complete within the budget,
  return `None`. The executor is closed with `shutdown(wait=False)`
  (the hung loader continues in the background best-effort; its
  return value is discarded).

**Important**: timed-out loaders are **best-effort terminated**;
the underlying thread may keep running until the loader itself
returns or the process exits. This is a known limitation of
Python (no `pthread_cancel` for arbitrary threads). Callers that
need a hard guarantee should compose the timeout *inside* their
`db_loader` (e.g. with `signal.alarm` or `asyncio.wait_for` in
an `asyncio.run` bridge). The M5.1 timeout is a **backstop**,
not a guarantee.

## Implementation

### Module-level helper (M5.1 sample)

`redis_string_manager.py` exports:

```python
def _call_db_loader_with_timeout(
    db_loader: Callable[[], Any],
    timeout_millis: int | None,
) -> Any:
    if timeout_millis is None:
        return db_loader()
    if timeout_millis <= 0:
        raise ValueError("loader_timeout_millis must be > 0 (or None)")
    executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="stampede-loader"
    )
    try:
        future = executor.submit(db_loader)
        try:
            return future.result(timeout=timeout_millis / 1000.0)
        except FuturesTimeoutError:
            return None
    finally:
        executor.shutdown(wait=False)
```

All 4 managers **import** this helper (not duplicate it). The
DRY constraint is honored.

### Per-method changes

The 10 public methods + their private `_stampede_load*` helpers
all got:

1. New keyword-only parameter `loader_timeout_millis: int | None = None`
2. Pass-through to the private helper
3. Validation: `loader_timeout_millis is not None and loader_timeout_millis <= 0 → ValueError`
4. Bilingual docstring (中 + 英) updated to mention the new parameter

| Manager | Public methods touched | Private helpers touched |
|---|---|---|
| `RedisStringManager` (sample) | `get_with_lock`, `get_from_string_with_lock` | `_stampede_load` |
| `RedisFieldManager` (M5.1 worker) | `get_with_lock`, `get_with_lock_typed`, `get_many_with_lock`, `get_object_from_hash_with_lock`, `get_from_hash_with_lock`, `get_from_hash_with_lock_typed` | `_stampede_load_field`, `_stampede_load_object`, `_stampede_load_many` |
| `RedisCollectionManager` (M5.1 worker) | `get_with_lock`, `get_from_set_with_lock` | `_stampede_load_set` |
| `RedisStructManager` (M5.1 worker) | `get_with_lock`, `get_with_lock_typed` | `_stampede_load` |

### Special cases

- **`_typed` variants** (Hash/Struct): the timeout governs the
  `db_loader()` call only. The deserialization of the loaded
  value (which uses the registered `reference` type) is
  in-process and bounded; it's not in the timeout envelope.
- **`get_many_with_lock`** (Hash batch): the timeout applies to
  the SINGLE `db_loader()` call that returns a dict for all
  missing keys. We do NOT loop per-key with separate timeouts —
  one batch = one loader invocation = one timeout envelope.
- **Stampede lock still released on timeout** (compare-and-delete
  via the existing `finally` block). This is what makes
  timeouts safe: the next caller can acquire cleanly.

## Test coverage

98 new tests across 3 new test files:

| File | Tests | Methods covered |
|---|---|---|
| `test_redis_string_manager_loader_timeout.py` (M5.1 sample) | 10 | 2 (String) |
| `test_redis_field_manager_loader_timeout.py` (M5.1 worker) | 56 | 6 (Field) |
| `test_redis_collection_struct_loader_timeout.py` (M5.1 worker) | 32 | 2 (Collection) + 2 (Struct) |

Each method covers the same 8-10 cases:

1. `loader_timeout_millis=None` preserves legacy behavior
2. Loader finishes within timeout → return value, cache populated
3. Loader exceeds timeout → return `None`, no cache write
4. Loader raises → exception propagates, lock released
5. `loader_timeout_millis=0` → `ValueError`
6. `loader_timeout_millis<0` → `ValueError`
7. Cache-hit path unaffected by `loader_timeout_millis`
8. After timeout, next call can acquire lock cleanly
9. (Function variants) StringFunction-style method also accepts kwarg
10. Concurrent timed-out loaders funnel to small constant

For `get_many_with_lock` additional cases:
- Loader exceeds timeout → no cache write, partial result handling
- Loader within timeout + partial hit → all loaded values written back

## Validation

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python
source .venv/bin/activate

# Per-file new tests
python -m pytest components/cache/cache-redis/tests/test_redis_string_manager_loader_timeout.py -v
# → 10 passed
python -m pytest components/cache/cache-redis/tests/test_redis_field_manager_loader_timeout.py -v
# → 56 passed
python -m pytest components/cache/cache-redis/tests/test_redis_collection_struct_loader_timeout.py -v
# → 32 passed

# Full suite
python -m pytest components/cache/cache-core/tests/ components/cache/cache-redis/tests/ -q
# → 560 passed, 4 skipped, 0 failures
```

(0 new failures; the 1 pre-existing flaky keyspace test passed
in the worker's run.)

## Trade-offs and what we learned

### Why keyword-only (`*` separator) and not positional

A positional parameter would be a breaking change for the 10
existing callers. The `*, loader_timeout_millis: int | None = None`
syntax forces callers to write
`get_with_lock(key, ttl, loader, loader_timeout_millis=100)` —
explicit, named, future-proof. This matches the team's
"No `**kwargs` in public APIs" rule (per project memory).

### Why `executor.shutdown(wait=False)` instead of `wait=True`

`wait=True` would block the cache method until the hung loader
finally returns — defeating the purpose of the timeout. `wait=False`
lets the cache method return immediately; the executor's worker
thread is daemon-marked and reclaimed by Python when the loader
eventually returns (or at process exit). The loader's late
return value is **discarded** because the cache has already moved
on (we released the stampede lock; the next caller will see the
cache either populated or empty).

### Why we don't propagate the timeout into the stampede lock TTL

The Redis stampede lock TTL stays = `timeout_millis` (the cache
entry's TTL), independent of `loader_timeout_millis`. Rationale:

- A timed-out loader shouldn't hold the stampede lock longer
  than the cache entry it was about to publish. If we set
  `lock_ttl = loader_timeout_millis`, the lock would expire
  *before* the cache entry — losing the stampede defense for
  the very next caller.
- The current `executor.shutdown(wait=False)` already releases
  the lock immediately (via the `finally` block), so the
  `lock_ttl = timeout_millis` is a backstop for a process that
  crashes during the loader call. The backstop should be the
  cache TTL, not the loader timeout.

### Why `concurrent.futures` and not `asyncio`

`db_loader` is a sync callable (the contract is sync; the L2
manager methods are sync). Wrapping a sync callable in an
asyncio bridge is more code and more moving parts. A single-
worker `ThreadPoolExecutor` is the simplest correct mechanism
for a sync callable with a timeout.

If the cache methods are ever migrated to `async def`, this
helper can be replaced with `asyncio.wait_for` in a
synchronous bridge — but that's a separate refactor.

## Files changed

| File | Change |
|---|---|
| `redis_string_manager.py` (M5.1 sample) | + `_call_db_loader_with_timeout` helper (47 lines), `loader_timeout_millis` kwarg on 2 public + 1 private methods, bilingual docstring updates |
| `redis_field_manager.py` (M5.1 worker) | `loader_timeout_millis` kwarg on 6 public + 3 private methods, import `_call_db_loader_with_timeout` |
| `redis_collection_manager.py` (M5.1 worker) | `loader_timeout_millis` kwarg on 2 public + 1 private methods, import helper |
| `redis_struct_manager.py` (M5.1 worker) | `loader_timeout_millis` kwarg on 2 public + 1 private methods, import helper |
| `test_redis_string_manager_loader_timeout.py` | NEW (sample) — 10 tests |
| `test_redis_field_manager_loader_timeout.py` | NEW (worker) — 56 tests |
| `test_redis_collection_struct_loader_timeout.py` | NEW (worker) — 32 tests |

**Total: 4 source files modified + 3 test files added = 7 files,
~3,800 insertions / ~50 deletions.**

## Review gate

- ✅ `pytest components/cache/cache-redis/tests/test_redis_string_manager_loader_timeout.py -v` —
  10 passed
- ✅ `pytest components/cache/cache-redis/tests/test_redis_field_manager_loader_timeout.py -v` —
  56 passed
- ✅ `pytest components/cache/cache-redis/tests/test_redis_collection_struct_loader_timeout.py -v` —
  32 passed
- ✅ `pytest components/cache/cache-{core,redis}/tests/ -q` —
  560 passed, 4 skipped, 0 failures (vs 462 baseline before M5.1; +98 net)
- ✅ No cache-core Protocol changes
- ✅ No "from Java" / "翻译自" cross-language comments
- ✅ `_call_db_loader_with_timeout` is the single shared helper; no
  Lua / thread-pool duplication across the 4 managers

## Follow-ups

1. **R-M5.2 (designed, pending owner review)** — `L2DistributedCache.get_or_load()`
   for L1 + in-process stampede integration. Design doc at
   `docs/acceptance/R-M5-2-l1-stampede-design.md` (commit `7734524`).
2. **Hard loader termination** (M5.5 candidate) — Python doesn't
   support `pthread_cancel`; if a hard guarantee is ever needed,
   the caller must compose the timeout inside `db_loader`
   (`signal.alarm` for SIGALRM in main thread, `asyncio.run` with
   `wait_for` in a thread). Document the trade-off; don't try to
   hide it.
3. **Loader observability** (M5.6 candidate) — emit
   `loader.timed_out` counter / log when the timeout fires, so
   operators can detect misbehaving downstream systems.
4. **Negative cache** (M5.7 candidate) — when the loader times
   out, optionally write a short-TTL `None` entry so the next
   caller doesn't immediately retry. Trade-off: cache pollution
   vs thundering herd.
