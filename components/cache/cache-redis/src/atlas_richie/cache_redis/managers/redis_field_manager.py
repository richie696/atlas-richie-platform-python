"""Hash 类型缓存管理器。
----
``FieldOps`` + ``HashFunction`` 的 Redis 后端实现（M2）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisHashManager`` 的结构。
同时实现 cache-core 中的底层 ``FieldOps`` Protocol（字段级 Hash 访问）
与高层 ``HashFunction`` Protocol（防击穿 + 批量辅助）。``ProviderRegistrar``
的 ``field_ops()`` 与 ``hash_function()`` 返回同一个实例（Python 允许一个
类结构性地满足多个 Protocol）。

``FieldOps`` 与 ``HashFunction`` 之间方法名冲突（``set``、``increment``、
``decrement``）通过使用单一方法签名、并将额外参数默认设为无操作值解决
（``timeout_millis=0``、``delta=1``）。合并后的方法同时满足两个 Protocol
的签名；语义仅在是否应用 TTL 或自定义 delta 上有所不同。

防雪崩策略（对齐 Java）：仅在高层 ``set(key, field, value, timeout_millis)``
且 ``timeout_millis > 0`` 时生效。底层 ``FieldOps.set``（无 TTL 参数）
**不**附加防雪崩。

M2 + M4 中已实现：

- 单字段：``set``、``get``、``get_typed``、``exists``。
- 原子计数器：``increment``、``increment_by``、``increment_double``、
  ``decrement``、``decrement_by``（``delta=1`` 默认值供 ``FieldOps`` 调用方使用）。
- 多字段：``set_all``、``get_all``、``get_many_typed``、``get_many``。
- 元信息：``get_fields``、``size``、``remove``。
- 批量：``batch_set``。
- 防击穿（M4）：``get_with_lock``、``get_with_lock_typed``、
  ``get_from_hash_with_lock``、``get_from_hash_with_lock_typed``、
  ``get_object_from_hash_with_lock``、``get_many_with_lock``。

后续 R-### 里程碑中处理：

- 写入时的布隆过滤器集成（M5+）。
- 性能守卫包装（M5+）。

English
--------
Redis-backed `FieldOps` + `HashFunction` (M2 + M4).

Mirrors `cn.richie696.component.cache.redis.manage.RedisHashManager`
1:1 in Python. Implements **both** the low-level `FieldOps` Protocol
(field-level Hash access) and the high-level `HashFunction` Protocol
(stampede prevention + bulk helpers) from `cache-core`. The
`ProviderRegistrar.field_ops()` and `.hash_function()` return the
same instance (Python allows a class to satisfy multiple Protocols
structurally).

Method-name collisions between `FieldOps` and `HashFunction`
(`set`, `increment`, `decrement`) are resolved by using a single
signature per method with the extra parameter defaulting to a no-op
value (`timeout_millis=0`, `delta=1`). The merged method satisfies
both Protocols' signatures; semantics differ only in whether TTL or
a custom delta is applied.

Anti-avalanche policy (matches Java): applied on the high-level
`set(key, field, value, timeout_millis)` helper when `timeout_millis
> 0`. Low-level `FieldOps.set` (no TTL argument) does NOT add
anti-avalanche. The `*_with_lock` write path passes the caller-
supplied TTL through verbatim — the lock-holder is the canonical
writer and the caller owns any TTL jitter policy.

What's implemented in M2 + M4:

- Single-field: `set`, `get`, `get_typed`, `exists`.
- Atomic counters: `increment`, `increment_by`, `increment_double`,
  `decrement`, `decrement_by` (with `delta=1` default for the
  `FieldOps` callers).
- Multi-field: `set_all`, `get_all`, `get_many_typed`, `get_many`.
- Meta: `get_fields`, `size`, `remove`.
- Batch: `batch_set`.
- Stampede prevention (M4): `get_with_lock`, `get_with_lock_typed`,
  `get_from_hash_with_lock`, `get_from_hash_with_lock_typed`,
  `get_object_from_hash_with_lock`, `get_many_with_lock` — per-key
  (or per-(key, field) / per-batch) Lua stampede lock; lock losers
  poll the cache for `wait_budget_millis` (50 ms cadence).

What's deferred to later R-### milestones:

- Bloom filter integration on writes (M5+).
- Perf guard wrapping (M5+).
- Local (L2) cache integration on the `*_with_lock` path (M5+; the
  Java side consults the L2 cache before Redis; in M4 we trust the
  Redis cache as the single source of truth, matching the String
  sample).
"""

from __future__ import annotations

import hashlib
import secrets as _secrets
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Collection, Dict, Iterator, List, Set, TypeVar

from atlas_richie.cache_core.function.hash_function import HashFunction
from atlas_richie.cache_core.ops.field_ops import FieldOps

from .._perf_guard import RedisPerfGuard
from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value

# Re-use the per-key Lua stampede lock primitives from the String
# manager. The Lua scripts and the SET-NX / compare-and-delete helper
# signatures are identical for the Hash backend; we only need extra
# lock-key builders below to address per-(key, field) and per-batch
# scopes.
from .redis_string_manager import (
    _call_db_loader_with_timeout,
    _call_db_loader_with_timeout_ex,
    _is_negative,
    _make_stampede_lock_key,
    _stampede_acquire,
    _stampede_release,
    _NEGATIVE_SENTINEL,
)

T = TypeVar("T")

# Anti-avalanche TTL offset range (matches Java's
# `CacheFunction.getRandomExtraMillis()`).
_MIN_ANTI_AVALANCHE_MS = 60_000
_MAX_ANTI_AVALANCHE_MS = 600_000


def _anti_avalanche_ms() -> int:
    return (
        _secrets.randbelow(_MAX_ANTI_AVALANCHE_MS - _MIN_ANTI_AVALANCHE_MS)
        + _MIN_ANTI_AVALANCHE_MS
    )


# ── Stampede-prevention lock keys (M4) ───────────────────────────────
# The Lua `SET NX PX` / compare-and-delete logic is identical to the
# String backend; only the lock-key SHAPE differs. Per-key shapes:
#
# - `_make_field_lock_key`  → per (key, field); used by the single-
#   field `_with_lock` variants so concurrent reads of the same
#   field funnel to one db_loader.
# - `_make_object_lock_key` → per (key); used by the object variant
#   `get_object_from_hash_with_lock` (the whole hash is the
#   protected resource, since the object is stored under a single
#   reserved field name).
# - `_make_batch_lock_key`  → per (key, sorted-fields); used by
#   `get_many_with_lock`. Batches with the same set of fields funnel;
#   different sets do not contend. The hash uses a SHA-1 prefix of
#   the sorted, `|`-joined field list so the key is stable across
#   processes and short enough to keep the Redis keyspace readable.
_OBJECT_FIELD = "__obj__"  # reserved hash field for get_object_from_hash_with_lock


def _make_field_lock_key(
    backend: RedisDistributedCache, key: str, field: str
) -> str:
    return _make_stampede_lock_key(backend, f"{key}:{field}")


def _make_object_lock_key(
    backend: RedisDistributedCache, key: str
) -> str:
    return _make_stampede_lock_key(backend, key)


def _make_batch_lock_key(
    backend: RedisDistributedCache, key: str, fields: Collection[str]
) -> str:
    fields_token = "|".join(sorted(fields))
    digest = hashlib.sha1(fields_token.encode("utf-8")).hexdigest()[:16]
    return _make_stampede_lock_key(backend, f"{key}:batch:{digest}")


# Polling cadence for lock-loser re-reads (matches the String sample).
_STAMPEDE_POLL_INTERVAL_SECONDS = 0.05  # 50ms


@contextmanager
def _noop_cm() -> Iterator[None]:
    """Zero-cost `with`-block used when the perf guard is disabled.

    Mirrors `redis_string_manager._noop_cm`; defined here so the
    `with _noop_cm():` lines inside the manager methods compile
    without an extra attribute lookup.
    """
    yield


class RedisFieldManager(FieldOps, HashFunction):
    """Hash 类型缓存管理器。
    ----
    Redis 后端的 Hash 缓存管理器。

    同时实现 ``FieldOps``（底层字段访问）与 ``HashFunction``（高层业务辅助）。

    English
    --------
    Redis-backed Hash cache manager.

    Implements both `FieldOps` (low-level field access) and
    `HashFunction` (high-level business helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (for typed reads via
            `get_value_type`).
        perf: Optional `RedisPerfGuard` (R-M5.4). When provided
            AND enabled, the single-field `set`, multi-field
            `set_all` / `batch_set`, and `get_many` methods
            are instrumented with payload-size and batch-size
            checks per the configured thresholds.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
        perf: RedisPerfGuard | None = None,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._perf = perf

    # ── Internal helpers ───────────────────────────────────────────

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    # ══════════════════════════════════════════════════════════════
    # FieldOps (low-level)
    # ══════════════════════════════════════════════════════════════

    # ── Single field ───────────────────────────────────────────────

    def set(self, key: str, field: str, value: Any, timeout_millis: int = 0) -> None:
        """设置一个 Hash 字段；可选附带 TTL。
        ----
        合并 ``FieldOps.set(key, field, value)``（无 TTL）与
        ``HashFunction.set(key, field, value, timeout_millis)``（带 TTL）。
        当 ``timeout_millis > 0`` 时附加防雪崩偏移（高层策略）。

        English
        --------
        Set one field; optionally with TTL (HashFunction shape).

        Merges `FieldOps.set(key, field, value)` (no TTL) and
        `HashFunction.set(key, field, value, timeout_millis)` (with
        TTL). When `timeout_millis > 0`, applies the anti-avalanche
        offset (high-level policy).

        Args:
            key: 缓存 key。
            field: Hash 字段名。
            value: 字段值。
            timeout_millis: 可选过期时间（毫秒），``0`` 表示不设置。
        """
        encoded = encode_value(value)
        if self._perf is not None:
            self._perf.check_key_name_hint(key)
            self._perf.check_hash_field_payload("set", encoded)
        with self._perf.time_op("set") if self._perf is not None else _noop_cm():
            client = self._backend.raw_client()
            client.hset(self._k(key), field, encoded)
            if timeout_millis and timeout_millis > 0:
                client.hpexpire(
                    self._k(key), int(timeout_millis) + _anti_avalanche_ms(), field
                )

    def get(self, key: str, field: str, clazz: type) -> Any:
        raw = self._backend.raw_client().hget(self._k(key), field)
        return decode_value(raw, clazz)

    def get_typed(self, key: str, field: str, reference: type) -> Any:
        registered = self._infra.get_value_type(key)
        target = registered if registered is not None else reference
        return self.get(key, field, target if target is not None else str)

    def exists(self, key: str, field: str) -> bool:
        return bool(self._backend.raw_client().hexists(self._k(key), field))

    # ── Atomic counters ─────────────────────────────────────────────
    #
    # `FieldOps.increment(key, field)` and
    # `HashFunction.increment(key, field, delta)` are merged with
    # `delta=1` default. Same for `decrement`.

    def increment(self, key: str, field: str, delta: int = 1) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, int(delta))
        )

    def increment_by(self, key: str, field: str, delta: int) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, int(delta))
        )

    def increment_double(self, key: str, field: str, delta: float) -> float:
        return float(
            self._backend.raw_client().hincrbyfloat(
                self._k(key), field, float(delta)
            )
        )

    def decrement(self, key: str, field: str, delta: int = 1) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, -int(delta))
        )

    def decrement_by(self, key: str, field: str, delta: int) -> int:
        return int(
            self._backend.raw_client().hincrby(self._k(key), field, -int(delta))
        )

    # ── Multi field ────────────────────────────────────────────────

    def set_all(
        self, key: str, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        if not mapping:
            return
        if self._perf is not None:
            self._perf.check_key_name_hint(key)
            self._perf.check_hash_payload("set_all", mapping)
        with self._perf.time_op("set_all") if self._perf is not None else _noop_cm():
            client = self._backend.raw_client()
            encoded = {f: encode_value(v) for f, v in mapping.items()}
            client.hset(self._k(key), mapping=encoded)
            if timeout_millis and timeout_millis > 0:
                ttl = int(timeout_millis) + _anti_avalanche_ms()
                for field in encoded:
                    client.hpexpire(self._k(key), ttl, field)

    def get_all(self, key: str, clazz: type) -> Dict[str, Any]:
        raw_map = self._backend.raw_client().hgetall(self._k(key))
        if not raw_map:
            return {}
        out: Dict[str, Any] = {}
        for field, raw in raw_map.items():
            v = decode_value(raw, clazz)
            if v is not None:
                out[field] = v
        return out

    def get_many_typed(
        self, key: str, fields: Collection[str], reference: type
    ) -> List[Any]:
        if not fields:
            return []
        raws = self._backend.raw_client().hmget(self._k(key), list(fields))
        return [
            v
            for v in (decode_value(raw, reference) for raw in raws)
            if v is not None
        ]

    def get_many(
        self, key: str, fields: Collection[str], clazz: type
    ) -> Dict[str, Any]:
        if not fields:
            return {}
        if self._perf is not None:
            self._perf.check_batch_size("get_many", len(fields))
        with self._perf.time_op("get_many") if self._perf is not None else _noop_cm():
            raws = self._backend.raw_client().hmget(self._k(key), list(fields))
            out: Dict[str, Any] = {}
            for field, raw in zip(fields, raws):
                v = decode_value(raw, clazz)
                if v is not None:
                    out[field] = v
            return out

    # ── Meta ────────────────────────────────────────────────────────

    def get_fields(self, key: str) -> Set[str]:
        raw = self._backend.raw_client().hkeys(self._k(key))
        return {self._normalise_field(f) for f in raw or []}

    @staticmethod
    def _normalise_field(field: Any) -> str:
        if isinstance(field, bytes):
            return field.decode("utf-8", errors="replace")
        return str(field)

    def size(self, key: str) -> int:
        return int(self._backend.raw_client().hlen(self._k(key)))

    def remove(self, key: str, *fields: str) -> None:
        if not fields:
            return
        self._backend.raw_client().hdel(self._k(key), *fields)

    # ── Batch ───────────────────────────────────────────────────────

    def batch_set(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        """批量添加缓存到 Redis Hash 的方法。
        ----
        跨多个 Hash 批量写入。

        Mapping 形状：``{key1: {field1: v1, field2: v2}, ...}``。使用
        pipeline 一次往返完成批量写入；**非原子性**（对齐 Java 文档）。

        English
        --------
        Bulk set across many Hashes.

        Mapping shape: `{key1: {field1: v1, field2: v2}, ...}`. Use a
        pipeline so the whole batch is one round-trip; NOT atomic
        (per the Java doc).

        Args:
            mapping: 批量添加的缓存数据。
        """
        if not mapping:
            return
        if self._perf is not None:
            self._perf.check_batch_size("batch_set", len(mapping))
        with self._perf.time_op("batch_set") if self._perf is not None else _noop_cm():
            client = self._backend.raw_client()
            pipe = client.pipeline(transaction=False)
            for key, field_map in mapping.items():
                encoded = {f: encode_value(v) for f, v in field_map.items()}
                pipe.hset(self._k(key), mapping=encoded)
            pipe.execute()

    # ── Stampede prevention (M4) ────────────────────────────────────
    #
    # All six `*_with_lock` methods follow the same pattern, modelled
    # on the String backend's `get_with_lock` / `_stampede_load`:
    #
    #   1. Cache hit → return immediately. No lock, no db_loader.
    #   2. Try to acquire a per-(key, field) / per-(key) / per-batch
    #      Lua stampede lock. The lock TTL equals the cache TTL so
    #      a crashed holder cannot keep the lock longer than the
    #      cache entry it was about to publish.
    #   3. Lost the lock race → poll the cache for `wait_budget_millis`
    #      (50 ms cadence); return the published value, or `None` if
    #      the budget expires.
    #   4. We hold the lock → double-check the cache (another holder
    #      may have published between our first read and lock
    #      acquisition).
    #   5. Still missing → invoke `db_loader`. If it returns `None`,
    #      do NOT write to the cache and return `None`.
    #   6. Otherwise write the value(s) to the cache with the
    #      caller-supplied TTL (no anti-avalanche offset — the
    #      `*_with_lock` path is the canonical write path; the
    #      caller owns any TTL jitter policy).
    #   7. Release the lock via compare-and-delete (so a stale
    #      holder cannot clobber a lock re-acquired by a different
    #      request after our TTL expired).
    #
    # The stampede lock is the **cache-stampede** lock, NOT the
    # application-level `RedisLockManager` lock; the two are
    # independent and can coexist (the stampede lock guards the
    # cache miss path, the application lock guards whatever
    # business resource the cached value represents).
    #
    # `get_with_lock` and `get_from_hash_with_lock` are functionally
    # identical (both single-field HGET + lock + load) — they exist
    # separately to match the two Protocol surface areas
    # (`FieldOps` vs `HashFunction`). Same for the `_typed` pair.

    def _set_field_with_ttl(
        self, key: str, field: str, value: Any, timeout_millis: int
    ) -> None:
        """HSET one field + HPEXPIRE; NO anti-avalanche offset.

        Used by the `*_with_lock` write path (canonical writer is
        the lock-holder, so the caller owns TTL jitter).
        """
        client = self._backend.raw_client()
        client.hset(self._k(key), field, encode_value(value))
        if timeout_millis and timeout_millis > 0:
            client.hpexpire(self._k(key), int(timeout_millis), field)

    def _set_many_with_ttl(
        self, key: str, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        """HSET many fields + per-field HPEXPIRE; NO anti-avalanche."""
        if not mapping:
            return
        client = self._backend.raw_client()
        encoded = {f: encode_value(v) for f, v in mapping.items()}
        client.hset(self._k(key), mapping=encoded)
        if timeout_millis and timeout_millis > 0:
            ttl = int(timeout_millis)
            pipe = client.pipeline(transaction=False)
            for field in encoded:
                pipe.hpexpire(self._k(key), ttl, field)
            pipe.execute()

    # ── Negative-cache raw peek helpers (M5.7) ─────────────────────
    # The M5.7 negative marker is a bytes sentinel that the typed
    # `get(key, field, clazz)` read decodes through `decode_value`,
    # which may round-trip the sentinel into a `None` (or empty
    # str/list — anything that the typed read cannot distinguish
    # from "no value"). To detect the marker we have to read the
    # raw bytes directly with HGET. These helpers are M5.7-internal
    # — they are not part of the public API.

    def _peek_field_raw(self, key: str, field: str) -> bytes | None:
        """HGET raw bytes for a single field, or `None` if absent.

        Used only by the M5.7 negative-cache detect path.
        """
        return self._backend.raw_client().hget(self._k(key), field)

    def _peek_fields_raw(
        self, key: str, fields: Collection[str]
    ) -> Dict[str, bytes | None]:
        """HMGET raw bytes for a list of fields.

        Returns `{field: bytes_or_None}` (None for absent fields).
        Used only by the M5.7 negative-cache detect path on
        `_stampede_load_many`.
        """
        fields_list = list(fields)
        if not fields_list:
            return {}
        raw_values = self._backend.raw_client().hmget(
            self._k(key), fields_list
        )
        return dict(zip(fields_list, raw_values))

    def _merge_negative_markers(
        self,
        key: str,
        fields: List[str],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """For any `field` in `fields` that is missing from
        `result`, peek the raw bytes; if they are the M5.7 negative
        sentinel, the field is treated as "loader already
        determined no value" and is EXCLUDED from the returned
        dict (consistent with the M5.1 "full-miss timeout returns
        `{}`" contract — the marker is a cached "no value"
        answer, not a cached `None` value).

        Fields with real cached values stay in `result` untouched.
        """
        missing = [f for f in fields if f not in result]
        if not missing:
            return result
        try:
            raw = self._peek_fields_raw(key, missing)
        except Exception:
            return result
        # Negative markers translate to "field absent from result";
        # we drop the field entirely. Real `None` decoded values
        # would have been returned as `None` by the typed read
        # and so would already be in `result[f] = None` — we
        # never overwrite those with the marker's "absent" semantics.
        for f, raw_bytes in raw.items():
            if _is_negative(raw_bytes) and f in result:
                # Defensive: a `result` entry for this field would
                # mean a non-None decoded value, but the raw
                # bytes claim it's a negative marker. The typed
                # read should have raised before this, but in
                # case the data raced, drop it.
                del result[f]
        return result

    # ── Public surface: FieldOps ────────────────────────────────────

    def get_with_lock(
        self,
        key: str,
        field: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：单 Hash field。

        命中直接返回；未命中则获取该 (key, field) 的 stampede 锁（与
        ``LockFunction`` 业务锁**独立**），调用 ``db_loader`` 回源，回写
        缓存。其他并发 caller 在锁被持有时进入短暂的轮询重试，超出
        等待预算则返回 ``None``，由调用方决定是否再次重试。

        Args:
            key: 缓存键（Hash 资源键）。
            field: Hash 字段名。
            clazz: 反序列化目标类型。
            timeout_millis: 缓存 TTL（毫秒），同时也是 stampede 锁
                的持有超时。
            db_loader: 回源加载器；返回 ``None`` 表示无值（不写缓存）。
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。`None`（默认）= 沿用旧行为（不限时）；
                `> 0` = `db_loader` 在此时间内未完成则当作
                `None` 处理（不写缓存），让 caller 决定是否重试。
                超时的 loader 可能在后台继续运行（best-effort
                终止，详见 `_call_db_loader_with_timeout`）。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `RedisStringManager.get_with_lock`。
                仅在 TIMEOUT 时写；自然 `None` 不写。

        Returns:
            缓存值；未命中且加载失败或超时时为 ``None``；命中负缓存
            标记时同样为 ``None``。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof single-field load. On cache hit, returns the
        cached value directly. On cache miss, acquires a per-(key,
        field) stampede lock (independent of any application-level
        `LockFunction` lock the caller may also be holding), invokes
        `db_loader` on the lock-holder, writes the result back, and
        returns. Concurrent waiters that lose the lock race enter a
        short polling loop and re-read the cache; if the winner
        hasn't published within the wait budget, returns `None` and
        lets the caller decide whether to retry.

        M5.1: `loader_timeout_millis` adds a millisecond-level
        backstop on `db_loader`. `None` preserves legacy
        (unbounded) behavior. A timed-out loader returns `None`
        (no cache write). Exceptions from `db_loader` are
        re-raised unchanged.

        M5.7: `negative_cache_ttl_millis` writes a short-TTL
        negative marker on TIMEOUT so subsequent callers within
        the window return `None` without re-invoking the loader.

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getFromHashWithLock(key, hashKey, clazz, dbLoader, timeout)`.
        """
        return self._stampede_load_field(
            key, field, clazz, timeout_millis, db_loader,
            use_typed=False, reference=None,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    def get_with_lock_typed(
        self,
        key: str,
        field: str,
        reference: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：单 Hash field（运行时类型版本）。

        缓存读取通过 ``CacheInfrastructure.get_value_type`` 解析运行时
        类型（与 ``get_typed`` 一致）。当注册表未登记时回退到调用方传入
        的 ``reference``。锁、写回与 ``get_with_lock`` 一致。

        Args:
            key: 缓存键。
            field: Hash 字段名。
            reference: 目标类型引用（注册表未命中时使用）。
            timeout_millis: 缓存 TTL（毫秒）。
            db_loader: 回源加载器。
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            缓存值；未命中且加载失败或超时时为 ``None``；命中负缓存
            标记时同样为 ``None``。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof single-field load with a runtime-resolved
        type. Cache read resolves the type via
        `CacheInfrastructure.get_value_type`; falls back to the
        caller-supplied `reference` when the registry has no entry
        for the key. Locking and writeback are identical to
        `get_with_lock`. The `loader_timeout_millis` kwarg governs
        only the `db_loader()` call; the typed read (after the
        loader returns) is in-process and bounded. M5.7:
        `negative_cache_ttl_millis` opts into a short-TTL
        negative-cache marker on TIMEOUT.

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getFromHashWithLock(key, hashKey, reference, dbLoader,
        timeout)`.
        """
        return self._stampede_load_field(
            key, field, None, timeout_millis, db_loader,
            use_typed=True, reference=reference,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    def get_many_with_lock(
        self,
        key: str,
        fields: Collection[str],
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Dict[str, Any] | None],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Dict[str, Any]:
        """防缓存击穿：批量 Hash field。

        一次 HMGET 读取全部 fields；命中的直接使用，未命中的进入"待加载"
        列表。**整批**获取一个 stampede 锁（key 由 sorted fields 哈希
        得出），调用 ``db_loader`` 一次回源，最后将所有加载值写回缓存。

        锁与写回策略与单 field 版本一致；stampede 锁的粒度是 (key, 字段
        集合)，相同字段集合的并发批量调用会汇聚到一次 db_loader。

        Args:
            key: 缓存键。
            fields: Hash 字段名集合。
            clazz: 反序列化目标类型。
            timeout_millis: 缓存 TTL（毫秒）。
            db_loader: 回源加载器；返回 ``{field: value}`` 字典，
                返回 ``None`` 或空字典表示无值（不写缓存）。
            loader_timeout_millis: 可选 — M5.1：单次 `db_loader()`
                调用的毫秒级超时。`None`（默认）= 沿用旧行为（不限
                时）；`> 0` = `db_loader` 在此时间内未完成则当作
                `None` 处理（不写缓存），让 caller 决定是否重试。
                **不要**按字段循环使用多个超时 — 整批是单次 loader
                调用。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL。TIMEOUT 时向**所有未命中的字段**写一个负缓存
                标记；自然 `None` 不写。详见
                `RedisStringManager.get_with_lock` 文档。

        Returns:
            ``{field: value}`` 字典，键集合与传入 ``fields`` 一致；
            未命中且加载失败或超时时为 ``{}``（或已有的部分命中）。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof batch field load. One HMGET reads all
        fields; cached values are used directly, misses are
        collected into a "to-load" list. A single batch-level
        stampede lock (key derived from the sorted field set) is
        acquired; the holder calls `db_loader` once, and the
        loaded values are written back. Concurrent batch callers
        with the SAME field set funnel to one db_loader; different
        sets do not contend.

        M5.1: `loader_timeout_millis` bounds the SINGLE `db_loader()`
        call. Do NOT loop per-key with separate timeouts — the
        whole batch is one loader invocation.

        M5.7: on a TIMEOUT, `negative_cache_ttl_millis` writes a
        per-field negative marker (HSET + HPEXPIRE) so subsequent
        callers within the window see the missing fields as
        already-cached `None` (the read path uses
        `_is_negative(...)` to detect the marker). Only fires on
        TIMEOUT, never on a natural `None` / empty dict from
        the loader.

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getFromHashWithLock(key, hashKeys, clazz, dbLoader, timeout)`.
        """
        return self._stampede_load_many(
            key, fields, clazz, timeout_millis, db_loader,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    # ── Public surface: HashFunction ────────────────────────────────

    def get_object_from_hash_with_lock(
        self,
        key: str,
        clazz: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：Hash 对象（按对象整体缓存）。

        缓存形式：以 ``_OBJECT_FIELD`` 保留字段存储 ``encode_value``
        序列化后的对象；命中直接反序列化返回，未命中则加锁回源并写回。

        与单 field 版本的区别：锁粒度是 (key) 而非 (key, field)；
        写回只产生一个 hash field。

        Args:
            key: 缓存键。
            clazz: 反序列化目标类型。
            db_loader: 回源加载器。
            timeout_millis: 缓存 TTL（毫秒）。
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            缓存对象；未命中且加载失败或超时时为 ``None``；命中
            负缓存标记时同样为 ``None``。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof object load. The object is stored as a
        single reserved field (``_OBJECT_FIELD``) in the Hash;
        cache hit deserialises that field, cache miss acquires a
        per-key stampede lock, calls `db_loader`, and writes the
        result back. The lock granularity is the whole key (not a
        per-field lock) because the object is the protected unit.
        M5.7: `negative_cache_ttl_millis` writes a short-TTL
        negative marker on TIMEOUT.

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getObjectFromHashWithLock(key, clazz, dbLoader, timeout)`.
        """
        return self._stampede_load_object(
            key, clazz, timeout_millis, db_loader,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    def get_from_hash_with_lock(
        self,
        key: str,
        hash_key: str,
        clazz: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：Hash 单 field（业务级便捷方法）。

        与 ``FieldOps.get_with_lock`` 行为一致，仅参数顺序不同
        （key, hash_key, clazz, db_loader, timeout_millis），便于业务
        代码按 (资源键, 哈希键, 目标类型, 加载器, 超时) 的自然顺序书写。

        Args:
            key: 缓存键。
            hash_key: Hash 字段名。
            clazz: 反序列化目标类型。
            db_loader: 回源加载器。
            timeout_millis: 缓存 TTL（毫秒）。
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            字段值；未命中且加载失败或超时时为 ``None``；命中
            负缓存标记时同样为 ``None``。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof single-field load (business-facing
        convenience). Same semantics as `FieldOps.get_with_lock`,
        with a more ergonomic argument order. Honours
        `loader_timeout_millis` (M5.1) and
        `negative_cache_ttl_millis` (M5.7).

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getFromHashWithLock(key, hashKey, clazz, dbLoader, timeout)`.
        """
        return self._stampede_load_field(
            key, hash_key, clazz, timeout_millis, db_loader,
            use_typed=False, reference=None,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    def get_from_hash_with_lock_typed(
        self,
        key: str,
        hash_key: str,
        reference: type,
        db_loader: Callable[[], Any],
        timeout_millis: int,
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：Hash 单 field（运行时类型版本，业务级便捷方法）。

        缓存读取通过 ``CacheInfrastructure.get_value_type`` 解析运行时
        类型；与 ``get_with_lock_typed`` 行为一致，参数顺序按
        ``HashFunction`` 习惯。

        Args:
            key: 缓存键。
            hash_key: Hash 字段名。
            reference: 目标类型引用（注册表未命中时使用）。
            db_loader: 回源加载器。
            timeout_millis: 缓存 TTL（毫秒）。
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            字段值；未命中且加载失败或超时时为 ``None``；命中
            负缓存标记时同样为 ``None``。

        Raises:
            ValueError: ``timeout_millis <= 0``、``db_loader`` 为
                ``None``、``loader_timeout_millis <= 0``，或
                ``negative_cache_ttl_millis <= 0``。
            ``db_loader`` 自身抛出的异常会原样传播。

        English
        --------
        Stampede-proof single-field load with a runtime-resolved
        type, with the `HashFunction`-style argument order.
        Honours `loader_timeout_millis` (M5.1) and
        `negative_cache_ttl_millis` (M5.7).

        Mirrors `cn.richie696.component.cache.function.HashFunction.
        getFromHashWithLock(key, hashKey, reference, dbLoader,
        timeout)`.
        """
        return self._stampede_load_field(
            key, hash_key, None, timeout_millis, db_loader,
            use_typed=True, reference=reference,
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    # ══════════════════════════════════════════════════════════════
    # Stampede-prevention internals (M4)
    # ══════════════════════════════════════════════════════════════

    def _stampede_load_field(
        self,
        key: str,
        field: str,
        clazz: type | None,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        use_typed: bool,
        reference: type | None,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """Shared implementation for the four single-field `*_with_lock` variants.

        `use_typed` toggles whether the cache-hit read goes through
        `get_typed` (resolves the runtime type via
        `CacheInfrastructure.get_value_type`, falling back to
        `reference`) or through `get(key, field, clazz)`. The lock,
        writeback, and release path are identical for both.

        M5.1: `loader_timeout_millis` adds a millisecond-level
        backstop on `db_loader`. `None` preserves legacy (unbounded)
        behavior. A timed-out loader returns `None` (no cache
        write). Exceptions from `db_loader` are re-raised unchanged.

        M5.7: `negative_cache_ttl_millis` writes a bytes sentinel
        to the field (HSET + HPEXPIRE) on TIMEOUT only; subsequent
        callers within the window return `None` without re-invoking
        the loader. The read path uses `_is_negative(...)` to
        distinguish a real `None` / empty value from the marker.
        M5.7 detection runs BEFORE the typed `get()` to avoid
        serialisation errors on non-str clazz types.
        """
        self._validate_lock_args(
            timeout_millis, db_loader, loader_timeout_millis,
            negative_cache_ttl_millis,
        )

        # 1. Fast path. M5.7: detect the negative marker via a
        #    RAW HGET BEFORE the typed `get(...)` — the sentinel
        #    bytes may not be decodable through the user's `clazz`.
        raw_peek = self._peek_field_raw(key, field)
        if raw_peek is not None:
            if _is_negative(raw_peek):
                return None
            return self._read_field_for_lock(
                key, field, clazz, use_typed, reference
            )

        # 2. Cache miss: acquire the per-(key, field) stampede lock.
        request_id = uuid.uuid4().hex
        lock_key = _make_field_lock_key(self._backend, key, field)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            # 3. Lost the lock race. Poll until the winner publishes
            #    or the wait budget expires.
            published = self._wait_for_field_publication(
                key, field, clazz, use_typed, reference,
                wait_budget_millis=int(timeout_millis),
            )
            if _is_negative(self._peek_field_raw(key, field)):
                return None
            return published

        try:
            # 4. Double-check the cache (another holder may have
            #    published between our first read and lock acquisition).
            raw_peek = self._peek_field_raw(key, field)
            if raw_peek is not None:
                if _is_negative(raw_peek):
                    return None
                return self._read_field_for_lock(
                    key, field, clazz, use_typed, reference
                )
            # 5. Still missing → invoke the db_loader, optionally
            #    with a timeout. `_call_db_loader_with_timeout_ex`
            #    returns `(value, timed_out)`; we use the flag to
            #    decide whether to write a negative-cache marker
            #    (M5.7). The typed read (for the `_typed` variants)
            #    happens AFTER this returns, in-process and bounded.
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                db_loader, loader_timeout_millis
            )
            if value is None:
                # M5.7: TIMEOUT → write a per-field negative marker.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self._set_field_with_ttl(
                            key, field, _NEGATIVE_SENTINEL,
                            int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                return None
            # 6. Publish: HSET + HPEXPIRE with the caller-supplied
            #    TTL (no anti-avalanche; the lock-holder is the
            #    canonical writer).
            self._set_field_with_ttl(key, field, value, timeout_millis)
            return value
        finally:
            # 7. Compare-and-delete the stampede lock so a stale
            #    holder cannot clobber a lock re-acquired by a
            #    different request after our TTL expired.
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                # Non-fatal: the lock will expire on its own via
                # the PX TTL. Don't mask the method's actual
                # return value with a release error.
                pass

    def _stampede_load_object(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """Implementation for `get_object_from_hash_with_lock`.

        M5.1: `loader_timeout_millis` adds a millisecond-level
        backstop on `db_loader`. `None` preserves legacy (unbounded)
        behavior. A timed-out loader returns `None` (no cache
        write). Exceptions from `db_loader` are re-raised unchanged.

        M5.7: `negative_cache_ttl_millis` writes a bytes sentinel
        to ``_OBJECT_FIELD`` on TIMEOUT only; subsequent callers
        within the window return `None` without re-invoking the
        loader. M5.7 detection runs BEFORE the typed `get()`
        because the sentinel bytes are not valid JSON and would
        blow up `decode_value(..., dict)`.
        """
        self._validate_lock_args(
            timeout_millis, db_loader, loader_timeout_millis,
            negative_cache_ttl_millis,
        )

        # 1. Fast path. M5.7: detect the negative marker via a
        #    RAW HGET BEFORE the typed `get(...)` — the sentinel
        #    bytes are not valid JSON and `decode_value(sentinel,
        #    dict)` would raise `SerializationError`.
        raw_peek = self._peek_field_raw(key, _OBJECT_FIELD)
        if raw_peek is not None:
            if _is_negative(raw_peek):
                return None
            return self.get(key, _OBJECT_FIELD, clazz)

        # 2. Cache miss: acquire the per-key stampede lock.
        request_id = uuid.uuid4().hex
        lock_key = _make_object_lock_key(self._backend, key)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            published = self._wait_for_object_publication(
                key, clazz, wait_budget_millis=int(timeout_millis),
            )
            if _is_negative(self._peek_field_raw(key, _OBJECT_FIELD)):
                return None
            return published

        try:
            # 3. Double-check the cache (raw peek first to avoid
            #    JSON-decoding the sentinel).
            raw_peek = self._peek_field_raw(key, _OBJECT_FIELD)
            if raw_peek is not None:
                if _is_negative(raw_peek):
                    return None
                return self.get(key, _OBJECT_FIELD, clazz)
            # 4. Still missing → invoke the db_loader, optionally
            #    with a timeout. M5.7: check timed_out flag.
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                db_loader, loader_timeout_millis
            )
            if value is None:
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self._set_field_with_ttl(
                            key, _OBJECT_FIELD, _NEGATIVE_SENTINEL,
                            int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                return None
            # 5. Publish.
            self._set_field_with_ttl(key, _OBJECT_FIELD, value, timeout_millis)
            return value
        finally:
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                pass

    def _stampede_load_many(
        self,
        key: str,
        fields: Collection[str],
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Dict[str, Any] | None],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Dict[str, Any]:
        """Implementation for `get_many_with_lock`.

        M5.1: `loader_timeout_millis` bounds the SINGLE `db_loader()`
        call (which returns a dict for all missing keys). Do NOT
        loop per-key with separate timeouts — the whole batch is
        one loader invocation. A timed-out loader yields `None`
        here, which is treated the same as a "loader returned
        None" miss: no cache write, return whatever was already
        cached (or `{}`).

        M5.7: `negative_cache_ttl_millis` writes a per-field
        bytes sentinel (HSET + HPEXPIRE) on TIMEOUT for each
        missing field. Subsequent callers within the window
        see the missing fields as already-cached `None`. Only
        fires on TIMEOUT, never on a natural `None` / empty
        dict from the loader.
        """
        self._validate_lock_args(
            timeout_millis, db_loader, loader_timeout_millis,
            negative_cache_ttl_millis,
        )
        fields_list = list(fields)
        if not fields_list:
            return {}

        # 1. Fast path: HMGET all fields; only treat it as a full
        #    hit when EVERY requested field is present. M5.7:
        #    individual negative markers are detected via a raw
        #    HGET peek on the missing fields (so a "field missing
        #    because the previous call wrote a negative marker"
        #    is recognised as a hit rather than a miss that would
        #    re-acquire the lock).
        cached = self.get_many(key, fields_list, clazz)
        # M5.7: peek the raw bytes for ALL requested fields so we
        # can detect negative-cache markers before the typed
        # read's `decode_value` round-trip masks them as benign
        # strings. Without this, a "full hit" of negative markers
        # would be returned to the caller as a dict of sentinel
        # strings, which is neither "real value" nor "no value"
        # — the markers must be excluded.
        raw_peek_all = self._peek_fields_raw(key, fields_list)
        negative_in_all = {
            f for f, raw in raw_peek_all.items() if _is_negative(raw)
        }
        if negative_in_all:
            # Drop negative-marker fields from the cached dict.
            for f in negative_in_all:
                if cached and f in cached:
                    del cached[f]
            if not cached and len(negative_in_all) == len(fields_list):
                # Every requested field is a negative marker —
                # surface as `{}` (full-miss "no value" answer,
                # consistent with the M5.1 contract).
                return {}
        if cached and len(cached) == len(fields_list):
            return cached
        # M5.7: pre-fetch raw bytes to detect negative markers
        # for any fields that came back missing in the typed
        # read above. Negative markers are "no value" answers
        # and the field is therefore EXCLUDED from the result
        # (consistent with the M5.1 "full-miss timeout returns
        # `{}`" contract).
        missing_fields = [
            f for f in fields_list
            if (not cached or f not in cached) and f not in negative_in_all
        ]
        if not missing_fields:
            return cached if cached else {}

        # 2. Cache miss (or partial hit): acquire the per-(key,
        #    sorted-fields) batch stampede lock.
        request_id = uuid.uuid4().hex
        lock_key = _make_batch_lock_key(self._backend, key, fields_list)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            waited = self._wait_for_many_publication(
                key, fields_list, clazz,
                wait_budget_millis=int(timeout_millis),
            )
            # On lock loss, the winner may have published only a
            # subset; we can't add a db_loader round-trip, so return
            # whatever the wait surfaced (may be a partial hit or {}).
            # M5.7: also surface any negative markers we observe
            # on raw read as `None` in the result.
            if waited:
                waited = self._merge_negative_markers(
                    key, fields_list, waited,
                )
            return waited

        try:
            # 3. Double-check the cache.
            cached = self.get_many(key, fields_list, clazz)
            if cached and len(cached) == len(fields_list):
                return cached
            # 4. Still missing (or partial) → invoke the db_loader
            #    ONCE for the whole batch, optionally with a timeout.
            loaded, was_timed_out = _call_db_loader_with_timeout_ex(
                db_loader, loader_timeout_millis
            )
            if not loaded:
                # Loader returned None or empty dict. M5.7: on
                # TIMEOUT, optionally write a per-field negative
                # marker for each originally-missing field so
                # subsequent callers see them as already-cached
                # `None` within the TTL window.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self._set_many_with_ttl(
                            key,
                            {f: _NEGATIVE_SENTINEL for f in missing_fields},
                            int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                if cached:
                    # M5.7: still apply negative-marker merge to
                    # the partial hit so a previously-pending
                    # negative field is reported as `None`.
                    cached = self._merge_negative_markers(
                        key, fields_list, cached,
                    )
                    return cached
                return self._merge_negative_markers(
                    key, fields_list, {},
                )
            # 5. Publish all loaded values back to the hash.
            self._set_many_with_ttl(key, loaded, timeout_millis)
            # 6. Return the UNION of cached + loaded. The caller
            #    asked for `fields`; we owe them every one. Cached
            #    values that the loader didn't return stay in the
            #    result (e.g. a "skip" loader that only returns the
            #    fields it actually knows about).
            merged: Dict[str, Any] = dict(cached) if cached else {}
            for f, v in loaded.items():
                merged[f] = v
            return merged
        finally:
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                pass

    @staticmethod
    def _validate_lock_args(
        timeout_millis: int,
        db_loader: Callable[[], Any] | None,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> None:
        """Shared argument validation for the `*_with_lock` methods."""
        if timeout_millis is None or int(timeout_millis) <= 0:
            raise ValueError("timeout_millis must be > 0")
        if db_loader is None:
            raise ValueError("db_loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        if negative_cache_ttl_millis is not None and negative_cache_ttl_millis <= 0:
            raise ValueError(
                "negative_cache_ttl_millis must be > 0 (or None)"
            )

    def _read_field_for_lock(
        self,
        key: str,
        field: str,
        clazz: type | None,
        use_typed: bool,
        reference: type | None,
    ) -> Any:
        """Cache-hit read for `_stampede_load_field`.

        `use_typed=True` resolves the runtime type via
        `CacheInfrastructure.get_value_type`; `use_typed=False`
        uses the explicit `clazz` (falling back to `str` if None
        — mirrors the String backend's `get(key, str)` default).
        """
        if use_typed:
            return self.get_typed(key, field, reference if reference is not None else str)
        return self.get(key, field, clazz if clazz is not None else str)

    def _wait_for_field_publication(
        self,
        key: str,
        field: str,
        clazz: type | None,
        use_typed: bool,
        reference: type | None,
        *,
        wait_budget_millis: int,
    ) -> Any:
        """Poll HGET for up to `wait_budget_millis` (50 ms cadence)."""
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        while time.monotonic() < deadline:
            time.sleep(_STAMPEDE_POLL_INTERVAL_SECONDS)
            cached = self._read_field_for_lock(
                key, field, clazz, use_typed, reference
            )
            if cached is not None:
                return cached
        return None

    def _wait_for_object_publication(
        self, key: str, clazz: type, *, wait_budget_millis: int
    ) -> Any:
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        while time.monotonic() < deadline:
            time.sleep(_STAMPEDE_POLL_INTERVAL_SECONDS)
            cached = self.get(key, _OBJECT_FIELD, clazz)
            if cached is not None:
                return cached
        return None

    def _wait_for_many_publication(
        self, key: str, fields: List[str], clazz: type, *, wait_budget_millis: int
    ) -> Dict[str, Any]:
        """Poll HMGET; return the FULLY-LOADED dict, or whatever is
        cached when the budget expires (matches the String backend's
        "publish or give up" semantics on a per-call basis — a
        partial hit is still better than `None`).

        M5.7: any field whose raw bytes are the negative-cache
        marker is excluded from the returned dict (consistent
        with the "full-miss timeout returns `{}`" contract — a
        negative marker is a cached "no value" answer, not a
        cached `None` value).
        """
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        last: Dict[str, Any] = {}
        while time.monotonic() < deadline:
            time.sleep(_STAMPEDE_POLL_INTERVAL_SECONDS)
            cached = self.get_many(key, fields, clazz)
            # M5.7: drop any fields whose raw bytes are the
            # negative marker — the typed `get_many` would have
            # decoded them to a benign str, not a real value.
            try:
                raw_peek = self._peek_fields_raw(
                    key, [f for f in fields if f not in (cached or {})]
                )
                negative_present = {
                    f for f, raw in raw_peek.items()
                    if _is_negative(raw)
                }
            except Exception:
                negative_present = set()
            if cached:
                for f in list(cached.keys()):
                    if f in negative_present:
                        del cached[f]
            else:
                cached = {}
            if cached and len(cached) == len(fields):
                return cached
            last = cached
        return last


__all__ = ["RedisFieldManager"]
