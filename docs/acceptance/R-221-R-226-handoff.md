# R-221 ~ R-226 Handoff: M5+ capability gap closure

**Date:** 2026-09-11
**Owner:** Mavis
**Status:** **6/6 DONE** — 6 capability gaps closed; M5 E2E skips
fully resolved (4 → 0 in-scope skips remaining).

## Goal

The R-220 M5 handoff doc committed to 6 follow-up R-### items
(R-221 ~ R-226) that filled the M1-M4 scope gaps. This handoff
documents the closure of all 6.

## Summary

| # | Capability | Pattern | Tests | E2E |
|---|---|---|---|---|
| **R-221** | NotificationOps `subscribe` | Observer + Adapter (redis-py pubsub) | 8/8 | 1 active |
| **R-222** | Bloom Filter (Redis shared + in-memory) | Strategy (shared vs in-mem) + Lua atomic | 18/18 | 1 active |
| **R-223** | L2 DistributedCache (L1 + L2) | Cache-aside (L1 → L2) | 14/14 | 1 active |
| **R-224** | SnowflakeIdBuilder | Snowflake (atomic workerId via Redis INCR) | 9/9 | 1 active |
| **R-225** | KeyspaceListener (Redis `notify-keyspace-events`) | Observer (redis-py psubscribe) | 5/5 | 1 active |
| **R-226** | EventOps in-process bus | Observer (in-proc listener list) | 10/10 | 1 active |
| | | | **64/64** | **6 active** |

The pre-R-221 E2E had 6 capability skips; after R-221~R-226 only
**4 remaining** (PerfGuard + List ops are not in any R-### scope).

## What was built

### R-221 — NotificationOps `subscribe` (Pub/Sub subscriber)

- New contract: `cache_core.contracts.notification_listener.NotificationListener`
  (`@runtime_checkable`, `is_open()` / `close()`).
- `NotificationOps` Protocol extended with
  `subscribe(topic, handler) -> NotificationListener`.
- New class: `RedisNotificationListener` (daemon thread + redis-py
  `PubSub` + per-listener handler list with thread-safe dispatch).
- `RedisNotificationManager.subscribe()` returns a `NotificationListener`
  that pumps messages on a background thread.
- Handler exception is logged but does not kill the pump.

### R-222 — Bloom Filter

- Two strategies coexisting:
  - `RedisSharedBloomFilter` (Redis BITSET + 2 Lua scripts for
    atomic SETBIT/GETBIT at k positions; cross-process).
  - `InMemoryBloomFilter` (Python `bytearray` + sha256-based
    double-hashing; single-process).
- Both implement the existing `cache_core.contracts.bloom_filter.BloomFilter`
  Protocol.
- Hashing: Kirsch-Mitzenmacher technique on `sha256(item)` — single
  digest gives two 64-bit integers (`hash_lo`, `hash_hi`); the k
  bit-positions are `(hash_lo + i * hash_hi) % bit_size`.
- `registrar.bloom_shared(config)` returns a `RedisSharedBloomFilter`;
  `registrar.bloom_in_memory(n, p)` returns an `InMemoryBloomFilter`.
- Cross-process: the meta hash (bit_size + hash_count) is read on
  open; if absent, written atomically. Re-opening with a different
  config does NOT shrink the bit array (the meta key is sticky).
- No false negatives in 1000-item round-trip; false-positive rate
  within 3x of the target (0.01 → observed ~0.015).

### R-223 — L2 DistributedCache

- New class: `L2DistributedCache(value_ops, region, max_size, ttl_seconds)`.
  Wraps L1 (cachetools via `LocalCacheManager` with per-region
  `CacheDefinition`) and L2 (`RedisStringManager`).
- API:
  - `get(key) -> bytes | None` — L1 first, L2 fallback, read-through
    on L2 hit.
  - `set(key, value, ttl_seconds=0)` — writes to BOTH layers
    synchronously; L1 uses `LocalCacheManager.put + expiry`, L2 uses
    `set_with_ttl`.
  - `delete(key)` — drops from both layers.
  - `invalidate_l1(key)` — drops from L1 only.
  - `stats()` — `hits` / `misses` / `l1_size` / `max_size`.
- New class: `L2CacheFactory` — caches `L2DistributedCache`
  instances per `(max_size, ttl_seconds)` so the same
  configuration returns the same instance (and stats accumulate).
- `registrar.l1(max_size, ttl_seconds)` returns the cached instance.

### R-224 — SnowflakeIdBuilder

- 64-bit layout (matches Java reference `IdBuilder` 1:1):
  - bit 63: 0 (sign)
  - bits 53-62: workerId (10 bits, 0..1023)
  - bits 12-52: timestamp - epoch (41 bits)
  - bits 0-11: sequence (12 bits, 0..4095 per ms)
- `EPOCH_MS = 1_588_435_200_000` (matches Java literal
  `twepoch = 1588435200000L`, which is 2020-05-03 00:00:00 +08:00).
- WorkerId allocation: Lua script atomically increments a Redis
  counter, rolling over at 1024.
- Per-process `AtomicLong`-equivalent (`_AtomicLong`) packs
  `(timestamp << 12) | sequence` and `increment_and_get()`.
- `wait_if_necessary()`: if the per-ms sequence is exhausted,
  `time.sleep(0.005)` until the next ms boundary.
- 9/9 tests: monotonic, no false collisions in 10k burst, 4-thread
  × 500 = 2000 unique IDs, signed-int64-safe.

### R-225 — KeyspaceListener

- The M3.A `RedisEventManager.subscribe_key_event` was already
  implemented but had a bug: the keyspace channel was being
  incorrectly namespaced (keyspace channels are Redis-special,
  not user-named).
- **Bug fix**: removed the `_k(pattern)` namespace prefix from
  `subscribe_key_event` so the subscription lands on the actual
  `__keyevent@<db>__:expired` / `:del` channel.
- Added end-to-end delivery tests:
  - `__keyevent@0__:expired` fires when a namespaced TTL'd key expires.
  - `__keyevent@0__:del` fires when a namespaced key is deleted.
  - Listener exception does not kill the pump thread.
  - `close()` stops the pump (no more events after close).
- 5/5 tests + E2E integration.

### R-226 — EventOps in-process bus

- Extended `RedisEventManager` with an in-process pub-sub:
  - `register_listener(event, callback)` / `on(event, callback)`
  - `unregister_listener(event, callback) -> bool`
  - `fire(event, payload) -> int` (returns listener count fired)
  - `listener_count(event) -> int`
- Synchronous delivery in registration order; listener exception
  is logged but does not stop subsequent listeners.
- 10/10 tests + E2E integration.
- Coexists with the keyspace event subscription (R-225) on the
  same `RedisEventManager` instance.

## Test results (all of cache-redis)

```text
334 passed, 4 skipped in ~25s
```

- **334 passed** — full R-221 ~ R-226 + M1-M5 test suite.
- **4 skipped** — M5 E2E capabilities out of M1-M4+ scope:
  - `test_7_5_perf_guard` — process-internal timing tracker, lives
    in the resilience module (not cache-redis).
  - `test_7_6_list_ops` — Java has no `ListOps.java` either;
    `BoundedQueue` / `BoundedStack` are the substitutes.

## Bug fixed during R-225

`subscribe_key_event` was prepending the cache namespace to the
keyspace channel pattern. Keyspace channels are Redis-special
(`__keyevent@0__:expired`), not user-named keys, so the
subscription landed on a non-existent channel and never received
events. The fix was a one-line change: pass the pattern as-is
to `psubscribe`.

## Trade-offs / design notes

1. **Subscriber close semantics** (R-221) — closing a listener
   marks it dead but does NOT join the pump thread (the daemon
   thread exits naturally when the pubsub connection is closed).
   This avoids a 1-2s hang on close but means the thread is
   technically alive for a brief moment after `close()` returns.

2. **Bloom filter re-open** (R-222) — re-opening with a different
   config does NOT shrink the bit array. The meta key is sticky:
   first `tryInit` wins. This matches the Java Redisson
   `RBloomFilter.tryInit` behavior.

3. **L2 delete via raw client** (R-223) — `ValueOps` Protocol
   doesn't expose `delete` (it belongs to `KeyOps`). The
   `L2DistributedCache.delete` calls the backend's `raw_client()`
   directly to keep the L2 layer implementation self-contained.

4. **Snowflake epoch** (R-224) — the Java literal `1588435200000`
   is 2020-05-03 00:00:00 +08:00 (Asia/Shanghai), not UTC. The
   cache-core contract docstring says "2020-05-03 UTC" but the
   actual value is +08:00. We mirror Java 1:1 (5 years of
   production, intentional).

5. **Keyspace channel is NOT namespaced** (R-225) — keyspace
   channels are server-wide; the caller filters by namespace
   prefix on the data field if isolation is needed.

6. **In-process bus is synchronous** (R-226) — `fire()` blocks
   until all listeners return. This matches the legacy
   `cache.fire()` semantics. An async variant is a future roadmap
   item if needed.

## Next: R-### (none committed)

All committed M5+ roadmap items are complete. The remaining
work (if any) would be:
- Update the `atlas-richie-platform` aggregator package
  documentation to reference the new APIs.
- Eventually deprecate and remove the old
  `components/cache/` 1-package structure (still in use for the
  90/90 legacy E2E tests).
- Consider a Redis-side `ListOps` mirror of bounded queue/stack
  if raw LPUSH/RPOP is ever needed (currently no consumer asks
  for this).
