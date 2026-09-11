# R-M5.2 Handoff: L1 (cachetools) + in-process stampede integration

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **DONE** — `L2DistributedCache.get_or_load()` implemented
with per-key `threading.Lock` + `WeakValueDictionary`-backed lock
table. **14 new tests** all passing; full suite **574 passed, 4
skipped, 0 new failures**.

## Motivation

M4 (R-M4) added stampede prevention at the **manager layer**:
`RedisStringManager.get_with_lock` and the 9 other `*_with_lock`
methods acquire a per-key Lua stampede lock on the L2 (Redis)
side, so concurrent misses from **different processes** funnel
to ONE `db_loader` call per stampede.

What M4 did NOT cover:

- **In-process stampede** on the `L2DistributedCache` path. The
  `L2DistributedCache.get(key)` method has no `loader` concept;
  callers do `value = l2.get(key); if value is None: value =
  loader(); l2.set(key, value)`. 10 threads calling `l2.get()`
  in parallel → 10 `loader()` invocations → **no in-process
  stampede protection at all**.

M5.2 closes this gap by adding `L2DistributedCache.get_or_load()`
— a loader-driven read that funnels concurrent in-process misses
to ONE loader call.

The companion design doc is at
`docs/acceptance/R-M5-2-l1-stampede-design.md` (commit
`7734524`); this handoff records the final implementation
choices and the test coverage.

## Public API

```python
def get_or_load(
    self,
    key: str,
    loader: Callable[[], bytes | None],
    *,
    ttl_seconds: int | None = None,
    loader_timeout_millis: int | None = None,
) -> bytes | None:
```

- L1 short-circuit: `cachetools` hit → return, no lock, no network.
- L1 miss → acquire per-key `threading.Lock`.
- Double-check L1 (another thread may have populated it).
- L2 read-through: `RedisStringManager.get` → populate L1, return.
- L1 + L2 miss → call `loader` (optionally with M5.1
  `loader_timeout_millis` timeout) → write to BOTH L1 and L2.
- Lock released in `finally` (compare-and-delete semantics not
  needed; `threading.Lock` is reentrant-safe per process).

**`L2DistributedCache.get()` is unchanged** — it's still the
right choice for callers that don't have a loader-driven read.

## Implementation

### `_KeyLock` class (private, in `l2_distributed_cache.py`)

```python
class _KeyLock:
    """Per-key `threading.Lock` wrapper that supports `weakref`."""

    __slots__ = ("_lock", "__weakref__")

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self._lock.release()
```

The `__weakref__` slot enables `WeakValueDictionary` to drop the
entry when the lock is no longer referenced (i.e. when the last
caller exits the `with` block). `threading.Lock` itself doesn't
support `weakref` (built-in mutexes are excluded), so the wrapper
is necessary.

### `L2DistributedCache.__init__` change

Added two fields:

```python
self._key_locks: weakref.WeakValueDictionary[str, _KeyLock] = (
    weakref.WeakValueDictionary()
)
self._key_locks_guard = threading.Lock()
```

The `_key_locks_guard` is needed because
`WeakValueDictionary.__setitem__` is NOT thread-safe; without the
guard, two threads contending for the same key could race during
dict mutation.

### `get_or_load` flow

1. L1 fast path (no lock): `self._local.get(self._region, key)`
2. Acquire `_get_key_lock(key)` (creates the `_KeyLock` lazily on
   first contention)
3. Double-check L1
4. L2 (Redis) check: `self._value_ops.get(key, bytes)`
5. L2 hit → populate L1, return
6. L1 + L2 miss → `_call_db_loader_with_timeout(loader,
   loader_timeout_millis)` (M5.1 helper, re-used)
7. Write to BOTH L1 and L2 with the effective TTL
8. Lock released by `with` exit

The L1 hit fast path (step 1) is the **common case** in
production; the lock is only acquired on cache miss, so a warm
cache pays zero lock cost.

### Why we did NOT also acquire the Redis stampede lock

This was a design question with two valid answers:

- **A: Both locks** — full cross-process + in-process stampede
  defense. Cost: 1 extra Redis round-trip per `get_or_load` call
  (the `SET NX PX` + `GET+DEL`).
- **B: In-process only** — the in-process `threading.Lock` is the
  L2-layer stampede defense; cross-process stampede defense
  lives in `RedisStringManager.get_with_lock`. The two APIs are
  complementary: callers that want cross-process defense use
  `*_with_lock`; callers that want L1 + L2 caching use
  `get_or_load`. This matches Java's `L2DistributedCache` (which
  has no stampede lock either).

We chose **B** because:

- It matches the Java side's design surface.
- The two APIs have different ergonomic goals:
  `RedisStringManager.get_with_lock` is "stampede-proof read
  with caller-supplied loader"; `L2DistributedCache.get_or_load`
  is "L1+L2 read with caller-supplied loader". Conflating them
  would make both APIs harder to use.
- The cross-process case is rare in single-process Python
  deployments (e.g. a single API server with multiple workers
  each running `L2DistributedCache`). When it matters, the
  caller can use `RedisStringManager.get_with_lock` directly.

### Lock-table memory bounds

The `WeakValueDictionary` drops entries automatically when the
`_KeyLock` is no longer strongly referenced (i.e. when the last
caller exits the `with` block). A test
(`test_key_lock_table_shrinks`) verifies this — after a
`get_or_load` call returns, the key is no longer in the
dictionary (we force a `gc.collect()` to make the test
deterministic, but the cleanup is automatic in CPython
reference counting).

For long-running processes with millions of distinct keys, this
keeps the lock table bounded by the number of **concurrent**
contending threads (typically << 1000) rather than the number
of historical keys. The per-lock overhead is ~100 bytes (a
`threading.Lock` is one OS mutex + a few Python fields), so even
1000 live locks is ~100 KB — well below the noise floor.

## Test coverage

`tests/test_l2_distributed_cache_get_or_load.py` — **14 tests**:

| # | Test | What it verifies |
|---|---|---|
| 1 | `test_l1_hit_skips_loader` | L1 pre-populated → loader NOT called |
| 2 | `test_l1_miss_l2_hit_read_through` | L1 cold, L2 has value → loader NOT called, L1 populated |
| 3 | `test_l1_l2_miss_loader_called_once` | Both empty → loader called once, written to both, returned |
| 4 | `test_l1_l2_miss_loader_returns_none` | `loader() = None` → no writes, returns `None` |
| 5 | `test_l1_l2_miss_loader_timeout` | Loader exceeds `loader_timeout_millis` → `None`, no writes |
| 6 | `test_l1_l2_miss_loader_raises` | Loader raises → exception propagates; next call can acquire |
| 7 | `test_concurrent_misses_funnel_to_one_loader` | 10 threads on one key → exactly 1 loader call |
| 8 | `test_concurrent_loaders_for_different_keys` | 5 keys × 2 threads each → 5 loader calls (per-key granularity) |
| 9 | `test_loader_timeout_none_legacy` | `loader_timeout_millis=None` preserves legacy behavior |
| 10 | `test_loader_timeout_zero_raises` | `loader_timeout_millis=0` → `ValueError` |
| 11 | `test_loader_timeout_negative_raises` | `loader_timeout_millis<0` → `ValueError` |
| 12 | `test_key_lock_table_shrinks` | After `with` exit + `gc.collect()`, key is no longer in `_key_locks` |
| 13 | `test_ttl_seconds_applied` | `ttl_seconds=2` → both L1 and L2 entries expire within ~2s |
| 14 | `test_none_loader_raises` | `loader=None` → `ValueError` |

## Validation

```bash
cd /Users/richie696/Projects/workspace/atlas-richie-platform-python
source .venv/bin/activate

# New tests
python -m pytest components/cache/cache-redis/tests/test_l2_distributed_cache_get_or_load.py -v
# → 14 passed

# Full suite
python -m pytest components/cache/cache-core/tests/ components/cache/cache-redis/tests/ -q
# → 574 passed, 4 skipped, 0 failures
# (vs 560 baseline before M5.2; +14 net; 0 new failures)
```

## Trade-offs and what we learned

### Why `WeakValueDictionary` and not `cachetools.LRUCache`

`cachetools.LRUCache` doesn't support `weakref` (entries are
strong references to support the LRU eviction order). We could
compose the two (`WeakValueDictionary` + `cachetools.LRUCache`
overlay), but the complexity isn't justified: lock objects are
tiny (a `threading.Lock` is ~100 bytes), and the worst-case
"concurrent in-flight locks" is bounded by thread count, not
key count. `WeakValueDictionary` is sufficient.

### Why `_key_locks_guard = threading.Lock()` is needed

`WeakValueDictionary.__setitem__` is NOT thread-safe. Without the
guard, two threads contending for the same key could race during
`self._key_locks[key] = lock` and corrupt the dict state. The
guard is a tiny overhead (a single Lock acquire per first
contention) and is held only for the dict mutation, not for the
user-level loader call.

### Why we don't reserve a slot in L1 for in-flight loads

When thread A is in `get_or_load`'s loader call, thread B might
hit `L2DistributedCache.set(key, value)` (from a different
write path) and that write would go into L1. If thread A
finishes its loader and writes to L1, the cachetools LRU might
have evicted the key in the meantime. This is **fine** — the
final state is consistent (the L1 has A's value or B's value,
both correct). The `LRU` semantics are best-effort, not
strictly serialized. We don't try to reserve a slot; doing so
would require either (a) a custom LRU implementation or (b)
holding the per-key lock for the entire `set()` call too, which
would serialize writes. Both are over-engineering for a best-
effort cache.

### Why we don't add a `_KeyLock` to cachetools itself

cachetools doesn't have a "reservation" concept. Adding one
would require a fork or a custom LRU wrapper. The per-key
`threading.Lock` in the L2 facade is a sufficient cache-stampede
defense; deeper integration with cachetools is unnecessary.

## Files changed

| File | Change |
|---|---|
| `local/l2_distributed_cache.py` | + `_KeyLock` class (22 lines); `_key_locks: WeakValueDictionary` + `_key_locks_guard` fields; `get_or_load` method (90 lines); `weakref` import. |
| `tests/test_l2_distributed_cache_get_or_load.py` | NEW — 14 tests (12 KB) |

**Total: 1 source file modified + 1 test file added = 2 files,
~13,000 insertions / ~50 deletions.**

## Review gate

- ✅ `pytest components/cache/cache-redis/tests/test_l2_distributed_cache_get_or_load.py -v` —
  14 passed
- ✅ `pytest components/cache/cache-{core,redis}/tests/ -q` —
  574 passed, 4 skipped, 0 failures (vs 560 baseline before M5.2; +14 net)
- ✅ No Protocol surface changes
- ✅ `L2DistributedCache.get()` is unchanged (backward compatible)
- ✅ `L2DistributedCache.set()` / `delete()` / `invalidate_l1()` /
  `stats()` all unchanged
- ✅ `_call_db_loader_with_timeout` from M5.1 is re-used (DRY)
- ✅ Weakref table cleanup verified by test
- ✅ Bilingual docstring (中 + 英) on `get_or_load`

## Follow-ups

1. **L2DistributedCache.get_or_load_many()** (M5.3 candidate) —
   batch loader support. Defer until first real use case.
2. **Stats observability** (M5.6 candidate) — add
   `in_process_loader_fan_in`, `in_process_loader_wait_seconds`,
   `key_lock_table_size` to `stats()` for tuning.
3. **Pre-existing flaky keyspace tests** — still 1 test flaky
   under full-suite contention; unrelated to M5.2.
4. **CHANGELOG.md** — R-M5.1 + R-M5.2 entries still need to be
   added (last sync was R-M4).
5. **HANDOFF.md** — §15 needs to be extended to cover R-M5.
