"""字符串类型缓存管理器。
----
``ValueOps`` + ``StringFunction`` 的 Redis 后端实现（仅 M1）。

镜像 ``cn.richie696.component.cache.redis.manage.RedisStringManager`` 的结构。
同时实现 cache-core 中的底层 ``ValueOps`` Protocol 与高层 ``StringFunction``
Protocol。``ProviderRegistrar`` 通过 ``value_ops()`` 与 ``string_function()``
访问器暴露这同一个实例（Python 允许一个类结构性地满足多个 Protocol）。

``ValueOps`` 与 ``StringFunction`` 之间的方法名冲突（``increment``、
``decrement``、``increment_by``、``decrement_by``、``increment_double``）
通过使用单一方法签名、并将 ``timeout_millis`` 默认设为 ``0``（无操作）
解决。这与 Java 重载语义一致：``ValueOps.increment(key)`` 等价于
``StringFunction.increment(key, 0)``。高层辅助方法（``add_value``、
``add_value_if_absent``、``batch_add_to_string_with_ttl``）对调用方传入
的 TTL 附加防雪崩偏移 —— 这就是面向用户的策略；底层 ``set_with_ttl`` /
``set_if_absent_with_ttl`` / ``batch_set_with_ttl`` 原样透传 TTL。

M1 中已实现：

- 基本 set / get / set_if_absent / set_with_ttl / set_if_absent_with_ttl。
- 原子计数器：``increment``、``increment_by``、``increment_double``、
  ``decrement``、``decrement_by``（以及 ``ValueOps`` 中的 ``_with_ttl``
  变体）。
- 批量 set / get。
- 通过 ``CacheInfrastructure`` 注册表实现的类型化读取（``get_typed``）。
- ``StringFunction`` 别名：``add_value``、``add_value_simple``、
  ``add_value_if_absent[_simple]``、``batch_add_to_string[_with_ttl]``、
  ``batch_update_if_absent``、``get_from_string[_typed]``、
  ``get_value_map``、``get_objects``。

后续 R-### 里程碑中处理：

- ``*_with_lock`` 防击穿（M4：需要 ``RedisLockManager`` + 布隆过滤器 +
  L2 装配）。
- ``scan``（M3：需要 ``RedisKeyManager`` + SCAN cursor 处理）。
- 底层方法的防雪崩 TTL（已挂接在 StringFunction 辅助方法上；
  ValueOps 方法透传调用方传入的 TTL）。
- 布隆过滤器 ``put`` 集成（M4：``RedisSharedBloomFilter``）。
- 性能守卫包装（``RedisPerfGuard.checkStringWritePayload``、``checkBatchRead``）。

English
--------
Redis-backed `ValueOps` + `StringFunction` (M1 only).

Mirrors `cn.richie696.component.cache.redis.manage.RedisStringManager`
1:1 in Python. Implements **both** the low-level `ValueOps` Protocol
and the high-level `StringFunction` Protocol from `cache-core`. The
`ProviderRegistrar` exposes this single instance through both
`value_ops()` and `string_function()` accessors (Python allows a
class to satisfy multiple Protocols structurally).

Method-name collisions between `ValueOps` and `StringFunction`
(`increment`, `decrement`, `increment_by`, `decrement_by`,
`increment_double`) are resolved by using a single signature per
method with `timeout_millis` defaulting to `0` (no-op). This matches
the Java overload semantics: `ValueOps.increment(key)` is equivalent
to `StringFunction.increment(key, 0)`. The high-level helpers
(`add_value`, `add_value_if_absent`, `batch_add_to_string_with_ttl`)
add the anti-avalanche offset to the caller-supplied TTL — that is
the user-facing policy; the low-level `set_with_ttl` /
`set_if_absent_with_ttl` / `batch_set_with_ttl` pass the TTL through
unchanged.

What's implemented in M1:

- Basic set / get / set_if_absent / set_with_ttl / set_if_absent_with_ttl.
- Atomic counters: `increment`, `increment_by`, `increment_double`,
  `decrement`, `decrement_by` (and the `_with_ttl` variants in
  `ValueOps`).
- Batch set / get.
- Typed read (`get_typed`) via the `CacheInfrastructure` registry.
- `StringFunction` aliases: `add_value`, `add_value_simple`,
  `add_value_if_absent[_simple]`, `batch_add_to_string[_with_ttl]`,
  `batch_update_if_absent`, `get_from_string[_typed]`,
  `get_value_map`, `get_objects`.

What's deferred to later R-### milestones:

- `*_with_lock` stampede prevention (M4: needs `RedisLockManager` +
  Bloom filter + L2 wiring).
- `scan` (M3: needs `RedisKeyManager` + SCAN cursor handling).
- Anti-avalanche TTL on the LOW-LEVEL methods (already wired on the
  StringFunction helpers; the ValueOps methods pass through the
  caller-supplied TTL).
- Bloom filter `put` integration (M4: `RedisSharedBloomFilter`).
- Perf guard wrapping (`RedisPerfGuard.checkStringWritePayload`,
  `checkBatchRead`).
"""

from __future__ import annotations

import secrets as _secrets
import time
import uuid
from typing import Any, Callable, Collection, Dict, List

from atlas_richie.cache_core.function.string_function import StringFunction
from atlas_richie.cache_core.ops.value_ops import ValueOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value


# Anti-avalanche TTL offset range (matches Java's
# `CacheFunction.getRandomExtraMillis()`): uniform in
# `[60_000, 600_000)` ms.
_MIN_ANTI_AVALANCHE_MS = 60_000
_MAX_ANTI_AVALANCHE_MS = 600_000


def _anti_avalanche_ms() -> int:
    """Return a uniform random offset in [60s, 10min) milliseconds."""
    return (
        _secrets.randbelow(_MAX_ANTI_AVALANCHE_MS - _MIN_ANTI_AVALANCHE_MS)
        + _MIN_ANTI_AVALANCHE_MS
    )


# ── Stampede-prevention lock (M4) ────────────────────────────────────
# Per-key Lua-acquired lock, used by `get_with_lock` /
# `get_from_string_with_lock` to ensure only ONE caller hits the
# db_loader for a given cache key during a stampede. This is the
# cache-stampede lock, NOT the application-level distributed lock
# (which lives in `RedisLockManager`); the two are independent and
# can coexist — the stampede lock guards the cache miss path, the
# application lock guards whatever business resource the cached
# value represents.
#
# Key shape: `{namespace}:__stampede_lock__:{user_key}`. Distinct
# prefix from `__lock__:` (used by `RedisLockManager`) so the two
# never collide.
#
# Atomicity guarantees:
#   - `_STAMPEDE_ACQUIRE_LUA` is `SET NX PX` (Redis native atomic).
#   - `_STAMPEDE_RELEASE_LUA` is `GET` + `DEL` under Lua's single
#     thread, so a stale holder cannot release a lock re-acquired
#     by a different request after the original TTL expired.
_STAMPEDE_ACQUIRE_LUA = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then
    return ARGV[1]
end
return ''
"""

_STAMPEDE_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _make_stampede_lock_key(backend: RedisDistributedCache, user_key: str) -> str:
    return backend.make_key(f"__stampede_lock__:{user_key}")


def _stampede_acquire(
    client: Any, lock_key: str, request_id: str, ttl_millis: int
) -> bool:
    """Atomic SET NX PX. Returns True iff this caller now holds the stampede lock."""
    result = client.eval(
        _STAMPEDE_ACQUIRE_LUA, 1, lock_key, request_id, str(int(ttl_millis))
    )
    if isinstance(result, bytes):
        result = result.decode("utf-8", errors="replace")
    return bool(result)


def _stampede_release(client: Any, lock_key: str, request_id: str) -> bool:
    """Atomic compare-and-delete. Returns True iff we still held the lock."""
    result = client.eval(_STAMPEDE_RELEASE_LUA, 1, lock_key, request_id)
    if isinstance(result, bytes):
        result = result.decode("utf-8", errors="replace")
    return int(result) == 1


class RedisStringManager(ValueOps, StringFunction):
    """字符串类型缓存管理器。
    ----
    Redis 后端的 String/Value 缓存管理器。

    同时实现 ``ValueOps``（底层 KV / 计数器）与 ``StringFunction``
    （高层业务辅助）。

    English
    --------
    Redis-backed String/Value cache manager.

    Implements both `ValueOps` (low-level KV / counter) and
    `StringFunction` (high-level business helpers).

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (for typed reads via
            `get_value_type`).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    # ── Internal helpers ───────────────────────────────────────────

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    @staticmethod
    def _apply_ttl(client, key: str, timeout_millis: int) -> None:
        """Refresh the key's TTL (no-op when `timeout_millis` is 0/None)."""
        if timeout_millis and timeout_millis > 0:
            client.pexpire(key, int(timeout_millis))

    # ══════════════════════════════════════════════════════════════
    # ValueOps (low-level)
    # ══════════════════════════════════════════════════════════════

    # ── Read ────────────────────────────────────────────────────────

    def get(self, key: str, clazz: type) -> Any:
        raw = self._backend.get(key)
        return decode_value(raw, clazz)

    def get_typed(self, key: str, reference: type) -> Any:
        """Read with a runtime-resolved type.

        Java's `TypeReference<T>` is replaced by Python's `type[T]`.
        We look up the registered type via `CacheInfrastructure`; if
        none is registered, we default to the caller-supplied
        `reference` (or `str` if neither is available).
        """
        registered = self._infra.get_value_type(key)
        target = registered if registered is not None else reference
        return self.get(key, target if target is not None else str)

    def get_map(self, keys: Collection[str], reference: type) -> Dict[str, Any]:
        if not keys:
            return {}
        namespaced = [self._k(k) for k in keys]
        raws = self._backend.raw_client().mget(namespaced)
        out: Dict[str, Any] = {}
        for k, raw in zip(keys, raws):
            v = decode_value(raw, reference)
            if v is not None:
                out[k] = v
        return out

    def get_list(self, keys: Collection[str], reference: type) -> List[Any]:
        if not keys:
            return []
        namespaced = [self._k(k) for k in keys]
        raws = self._backend.raw_client().mget(namespaced)
        out: List[Any] = []
        for raw in raws:
            v = decode_value(raw, reference)
            if v is not None:
                out.append(v)
        return out

    # ── Write ───────────────────────────────────────────────────────

    def set(self, key: str, value: Any) -> None:
        self._backend.set(key, encode_value(value))

    def set_if_absent(self, key: str, value: Any) -> bool:
        result = self._backend.set(key, encode_value(value), if_absent=True)
        return bool(result)

    def set_with_ttl(self, key: str, value: Any, timeout_millis: int) -> None:
        self._backend.set(
            key, encode_value(value), ttl_millis=int(timeout_millis)
        )

    def set_if_absent_with_ttl(
        self, key: str, value: Any, timeout_millis: int
    ) -> bool:
        result = self._backend.set(
            key,
            encode_value(value),
            ttl_millis=int(timeout_millis),
            if_absent=True,
        )
        return bool(result)

    # ── Atomic counters ─────────────────────────────────────────────
    #
    # `ValueOps.increment(key)` and `StringFunction.increment(key, timeout_millis)`
    # are merged into one method. Default `timeout_millis=0` keeps the
    # low-level caller (no TTL refresh) and the high-level caller
    # (`add_value`-style with TTL refresh) both working.

    def increment(self, key: str, timeout_millis: int = 0) -> int:
        client = self._backend.raw_client()
        new_value = int(client.incr(self._k(key)))
        self._apply_ttl(client, self._k(key), timeout_millis)
        return new_value

    def increment_by(
        self, key: str, delta: int, timeout_millis: int = 0
    ) -> int:
        client = self._backend.raw_client()
        new_value = int(client.incrby(self._k(key), int(delta)))
        self._apply_ttl(client, self._k(key), timeout_millis)
        return new_value

    def increment_by_with_ttl(
        self, key: str, delta: int, timeout_millis: int
    ) -> int:
        return self.increment_by(key, delta, timeout_millis)

    def increment_double(
        self, key: str, delta: float, timeout_millis: int = 0
    ) -> float:
        client = self._backend.raw_client()
        new_value = float(client.incrbyfloat(self._k(key), float(delta)))
        self._apply_ttl(client, self._k(key), timeout_millis)
        return new_value

    def decrement(self, key: str, timeout_millis: int = 0) -> int:
        client = self._backend.raw_client()
        new_value = int(client.decr(self._k(key)))
        self._apply_ttl(client, self._k(key), timeout_millis)
        return new_value

    def decrement_by(
        self, key: str, delta: int, timeout_millis: int = 0
    ) -> int:
        client = self._backend.raw_client()
        new_value = int(client.decrby(self._k(key), int(delta)))
        self._apply_ttl(client, self._k(key), timeout_millis)
        return new_value

    def decrement_by_with_ttl(
        self, key: str, delta: int, timeout_millis: int
    ) -> int:
        return self.decrement_by(key, delta, timeout_millis)

    # ── Batch ───────────────────────────────────────────────────────

    def batch_set(self, mapping: Dict[str, Any]) -> None:
        if not mapping:
            return
        encoded = {self._k(k): encode_value(v) for k, v in mapping.items()}
        self._backend.raw_client().mset(encoded)

    def batch_set_with_ttl(
        self, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        if not mapping:
            return
        # Low-level op: pass the TTL through unchanged (no anti-
        # avalanche offset). Anti-avalanche is a high-level policy
        # applied by `add_value` / `batch_add_to_string_with_ttl` etc.
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for k, v in mapping.items():
            pipe.set(self._k(k), encode_value(v), px=int(timeout_millis))
        pipe.execute()

    def batch_set_if_absent(self, mapping: Dict[str, Any]) -> None:
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for k, v in mapping.items():
            pipe.set(self._k(k), encode_value(v), nx=True)
        pipe.execute()

    def batch_set_if_absent_with_ttl(
        self, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for k, v in mapping.items():
            pipe.set(self._k(k), encode_value(v), px=int(timeout_millis), nx=True)
        pipe.execute()

    # ── Stampede prevention (M4) ────────────────────────────────────

    def get_with_lock(
        self,
        key: str,
        timeout_millis: int,
        db_loader: Callable[[], str | None],
    ) -> str | None:
        """防缓存击穿：String 类型。

        命中直接返回；未命中则获取本方法的 stampede 锁（与
        `LockFunction` 业务锁**独立**），调用 `db_loader` 回源，回写
        缓存。其他并发 caller 在锁被持有时进入短暂的轮询重试，超出
        等待预算则返回 `None`，由调用方决定是否再次重试。

        Args:
            key: 缓存键
            timeout_millis: 缓存 TTL（毫秒），同时也是 stampede 锁
                的持有超时
            db_loader: 回源加载器；返回 `None` 表示无值（不写缓存）

        Returns:
            缓存值；未命中且加载失败时为 `None`。

        Raises:
            ValueError: `timeout_millis <= 0` 或 `db_loader` 为 `None`。

        English
        --------
        Stampede-proof String load. On cache hit, returns the cached
        value directly. On cache miss, acquires a per-key stampede
        lock (independent of any application-level `LockFunction`
        lock the caller may also be holding), invokes `db_loader`
        on the lock-holder, writes the result back to the cache,
        and returns. Concurrent waiters that lose the lock race
        enter a short polling loop and re-read the cache; if the
        winner hasn't published within the wait budget, returns
        `None` and lets the caller decide whether to retry.
        """
        return self._stampede_load(
            key, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
        )

    def get_from_string_with_lock(
        self, key: str, db_loader: Callable[[], str | None], timeout_millis: int
    ) -> str | None:
        """防缓存击穿：String 类型（业务级便捷方法）。

        与 `ValueOps.get_with_lock` 行为一致，仅参数顺序不同（key,
        db_loader, timeout_millis），便于业务代码按 (资源键, 加载器,
        超时) 的自然顺序书写。

        Args:
            key: 缓存键
            db_loader: 回源加载器
            timeout_millis: 缓存 TTL（毫秒）

        Returns:
            缓存值；未命中且加载失败时为 `None`。

        English
        --------
        Stampede-proof String load (business-facing convenience).
        Same semantics as `get_with_lock`, with a more ergonomic
        argument order: `(key, db_loader, timeout_millis)`.
        """
        return self._stampede_load(
            key, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
        )

    def _stampede_load(
        self,
        key: str,
        timeout_millis: int,
        db_loader: Callable[[], str | None],
        *,
        wait_budget_millis: int,
    ) -> str | None:
        """Shared implementation for `get_with_lock` + `get_from_string_with_lock`.

        Returns the cached value (on hit) or the loaded value
        (after a successful db_loader round-trip). Returns `None`
        if the db_loader returned `None` or if a competing stampede
        lock holder didn't publish within the wait budget.
        """
        if timeout_millis <= 0:
            raise ValueError("timeout_millis must be > 0")
        if db_loader is None:
            raise ValueError("db_loader is required")

        # 1. Fast path: cache hit → return immediately. No Redis lock
        #    acquired, no db_loader call.
        cached = self.get(key, str)
        if cached is not None:
            return cached

        # 2. Cache miss: try to acquire the per-key stampede lock.
        #    The lock's TTL is the same as the cache TTL, so a
        #    crashed lock-holder can't hold the lock for longer
        #    than the cache entry it was about to publish.
        request_id = uuid.uuid4().hex
        lock_key = _make_stampede_lock_key(self._backend, key)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            # 3. Lost the lock race. Poll the cache for up to
            #    `wait_budget_millis` (50ms cadence). If the winner
            #    publishes, return the cached value. If not, give
            #    up and let the caller decide.
            return self._wait_for_publication(
                key, wait_budget_millis=wait_budget_millis
            )

        # 4. We hold the stampede lock. Double-check the cache
        #    (another holder may have published between our first
        #    read and our lock acquisition).
        try:
            cached = self.get(key, str)
            if cached is not None:
                return cached
            # 5. Still missing → invoke the db_loader.
            value = db_loader()
            if value is None:
                return None
            # 6. Publish: write to the cache. Note: we use the
            #    caller-supplied TTL verbatim. The anti-avalanche
            #    offset is intentionally NOT applied here — the
            #    `*_with_lock` path is the canonical write path
            #    and the caller is responsible for any TTL
            #    jitter policy.
            self.set_with_ttl(key, value, timeout_millis)
            return value
        finally:
            # 7. Release the stampede lock (compare-and-delete so a
            #    stale holder can't release a lock re-acquired by
            #    someone else after our TTL expired).
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                # Release failures are non-fatal: the lock will
                # expire on its own via the PX TTL. Don't mask the
                # method's actual return value with a release
                # error.
                pass

    def _wait_for_publication(
        self, key: str, *, wait_budget_millis: int
    ) -> str | None:
        """Poll the cache for up to `wait_budget_millis` (50ms cadence).

        Returns the published value, or `None` if no one published
        within the budget.
        """
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        poll_interval_seconds = 0.05  # 50ms
        while time.monotonic() < deadline:
            time.sleep(poll_interval_seconds)
            cached = self.get(key, str)
            if cached is not None:
                return cached
        return None

    def batch_add_to_string(self, mapping: Dict[str, Any]) -> None:
        """High-level batch set WITHOUT TTL (anti-avalanche N/A)."""
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for k, v in mapping.items():
            pipe.set(self._k(k), encode_value(v))
        pipe.execute()

    def batch_add_to_string_with_ttl(
        self, mapping: Dict[str, Any], timeout_millis: int
    ) -> None:
        """High-level batch set WITH TTL + anti-avalanche offset."""
        if not mapping:
            return
        client = self._backend.raw_client()
        pipe = client.pipeline(transaction=False)
        for k, v in mapping.items():
            pipe.set(
                self._k(k),
                encode_value(v),
                px=int(timeout_millis) + _anti_avalanche_ms(),
            )
        pipe.execute()

    def add_value(self, key: str, value: Any, timeout_millis: int) -> None:
        """High-level set with TTL + anti-avalanche offset."""
        client = self._backend.raw_client()
        client.set(
            self._k(key),
            encode_value(value),
            px=int(timeout_millis) + _anti_avalanche_ms(),
        )

    def add_value_simple(self, key: str, value: Any) -> None:
        self.set(key, value)

    def add_value_if_absent(
        self, key: str, value: Any, timeout_millis: int
    ) -> bool:
        """High-level set-if-absent with TTL + anti-avalanche offset."""
        client = self._backend.raw_client()
        result = client.set(
            self._k(key),
            encode_value(value),
            px=int(timeout_millis) + _anti_avalanche_ms(),
            nx=True,
        )
        return bool(result)

    def add_value_if_absent_simple(self, key: str, value: Any) -> bool:
        return self.set_if_absent(key, value)

    def batch_update_if_absent(
        self, batch_update: Dict[str, Any], timeout_millis: int
    ) -> None:
        """MSET + per-key EXPIRE (anti-avalanche applied to each TTL)."""
        if not batch_update:
            return
        self.batch_set(batch_update)
        if timeout_millis and timeout_millis > 0:
            client = self._backend.raw_client()
            pipe = client.pipeline(transaction=False)
            for k in batch_update:
                pipe.pexpire(
                    self._k(k), int(timeout_millis) + _anti_avalanche_ms()
                )
            pipe.execute()

    def get_value_map(
        self, keys: Collection[str], reference: type
    ) -> Dict[str, Any]:
        return self.get_map(keys, reference)

    def get_objects(self, keys: Collection[str], reference: type) -> List[Any]:
        return self.get_list(keys, reference)

    def get_from_string(self, key: str, clazz: type) -> Any:
        return self.get(key, clazz)

    def get_from_string_typed(self, key: str, reference: type) -> Any:
        return self.get_typed(key, reference)

    def scan(self, match: str, count: int, clazz: type) -> Dict[str, Any]:
        """SCAN-based wildcard lookup.

        M3 work — requires `RedisKeyManager` to share the SCAN
        cursor; for M1 we delegate to SCAN-iter with a warning.
        """
        out: Dict[str, Any] = {}
        for k in self._backend.keys(match):
            v = self.get(k, clazz)
            if v is not None:
                out[k] = v
        return out


__all__ = ["RedisStringManager"]
