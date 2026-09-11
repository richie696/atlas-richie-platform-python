"""``StructOps`` 的 Redis 后端实现（M3.C，Python 独有）。
----
实现 cache-core 中的 ``StructOps`` Protocol。这是 **Python 独有** 的
数据结构 —— Java 参考库中并没有直接对应物。意图是将一个完整的
JSON / pickle 对象视作单一缓存值，并配备专用的 ``refresh`` 辅助方法
（在乐观锁下进行读-改-写）。

``refresh`` 使用 ``WATCH`` + ``MULTI`` + ``EXEC`` 保证原子性：

1. WATCH 目标 key。
2. 读取当前值。
3. 通过用户提供的 ``func`` 计算新值。
4. MULTI / SET / EXEC。
5. 若 key 在 WATCH 与 EXEC 之间被修改，触发 ``WatchError`` 并从第 1 步重试。

English
--------
Redis-backed `StructOps` (M3.C, Python-only).

Implements the `StructOps` Protocol from `cache-core`. This is a
**Python-only** data structure — the Java reference library has no
direct equivalent. The intent is to treat a whole JSON / pickle
object as a single cache value with its own dedicated `refresh`
helper (read-modify-write under an optimistic lock).

`refresh` uses `WATCH` + `MULTI` + `EXEC` for atomicity:

1. WATCH the key.
2. Read the current value.
3. Compute the new value via the user-supplied `func`.
4. MULTI / SET / EXEC.
5. If the key changed between WATCH and EXEC, `WatchError` fires
   and we retry from step 1.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, TypeVar

import redis as redis_lib
from atlas_richie.cache_core.ops.struct_ops import StructOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import decode_value, encode_value
from .redis_string_manager import (
    _call_db_loader_with_timeout,
    _call_db_loader_with_timeout_ex,
    _is_negative,
    _make_stampede_lock_key,
    _NEGATIVE_SENTINEL,
    _stampede_acquire,
    _stampede_release,
)

T = TypeVar("T")


class RedisStructManager(StructOps):
    """Redis 后端的 struct / object 缓存管理器。
    ----
    将整个 JSON / pickle 对象视作单一缓存值，并提供基于 ``WATCH`` 的
    乐观锁刷新。

    English
    --------
    Redis-backed struct / object cache manager.

    Args:
        backend: The Redis transport wrapper.
        infra: The `CacheInfrastructure` (used by `get_typed`).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    def get(self, key: str, clazz: type) -> Any:
        raw = self._backend.raw_client().get(self._k(key))
        return decode_value(raw, clazz)

    def get_typed(self, key: str, reference: type) -> Any:
        registered = self._infra.get_value_type(key)
        target = registered if registered is not None else reference
        return self.get(key, target if target is not None else str)

    def set(self, key: str, value: Any) -> None:
        self._backend.raw_client().set(self._k(key), encode_value(value))

    def set_with_ttl(
        self, key: str, value: Any, timeout_millis: int
    ) -> None:
        self._backend.raw_client().set(
            self._k(key), encode_value(value), px=int(timeout_millis)
        )

    def refresh(
        self, key: str, func: Callable[[Any], Any]
    ) -> Any:
        """Atomic read-modify-write.

        The `func` receives the current value (or `None` if absent)
        and returns the new value. We retry on `WatchError` (the
        key changed between WATCH and EXEC) up to 100 times — the
        pattern is well-suited to low-contention counters and short
        critical sections. For genuine hot keys the caller should
        switch to `lock_ops.optimistic_lock` (M4).
        """
        import time as _time

        client = self._backend.raw_client()
        ns_key = self._k(key)
        for _attempt in range(100):
            try:
                with client.pipeline() as pipe:
                    pipe.watch(ns_key)
                    current_raw = pipe.get(ns_key)
                    current = (
                        decode_value(current_raw, str)
                        if current_raw is not None
                        else None
                    )
                    new_value = func(current)
                    pipe.multi()
                    pipe.set(ns_key, encode_value(new_value))
                    pipe.execute()
                return new_value
            except redis_lib.WatchError:
                # Tiny backoff to break the livelock between racing
                # threads; the cost is negligible at our scale.
                _time.sleep(0.0001)
                continue
        # 100 retries exhausted — fall back to a non-atomic write.
        # The caller should switch to `lock_ops` for true atomicity
        # under high contention.
        current_raw = client.get(ns_key)
        current = (
            decode_value(current_raw, str)
            if current_raw is not None
            else None
        )
        new_value = func(current)
        client.set(ns_key, encode_value(new_value))
        return new_value

    def get_with_lock(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：结构化对象（``StructOps.get_with_lock``）。

        命中直接返回；未命中则获取本方法的 stampede 锁（与
        ``LockFunction`` 业务锁**独立**），调用 ``db_loader`` 回源，
        回写缓存。其他并发 caller 在锁被持有时进入短暂的轮询重试，
        超出等待预算则返回 ``None``，由调用方决定是否再次重试。

        Args:
            key: 缓存键
            clazz: 反序列化目标类型
            timeout_millis: 缓存 TTL（毫秒），同时也是 stampede 锁
                的持有超时
            db_loader: 回源加载器；返回 ``None`` 表示无值（不写缓存）
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。`None`（默认）= 沿用旧行为（不限时）；
                `> 0` = `db_loader` 在此时间内未完成则当作
                `None` 处理（不写缓存），让 caller 决定是否重试。
                超时的 loader 可能在后台继续运行（best-effort
                终止，详见 `_call_db_loader_with_timeout`）。
            negative_cache_ttl_millis: 可选 — M5.7：仅当
                `db_loader` 因 `loader_timeout_millis` **超时**而
                未返回（loader 自然返回 `None` 仍按 miss 处理）时，
                写一个短 TTL 的"负缓存"标记，让后续 caller 在
                TTL 窗口内直接返回 `None` 而不再调用 loader。
                缓解下游降级时的 thundering herd。`None`（默认）
                = 不写负缓存。

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
        Stampede-proof struct load. On cache hit, returns the cached
        value directly. On cache miss, acquires a per-key stampede
        lock (independent of any application-level ``LockFunction``
        lock), invokes ``db_loader`` on the lock-holder, writes the
        result back to the cache, and returns. Concurrent waiters
        that lose the lock race enter a short polling loop and
        re-read the cache; if the winner hasn't published within
        the wait budget, returns ``None``.

        M5.1: `loader_timeout_millis` adds a millisecond-level
        backstop on `db_loader`. `None` preserves legacy
        (unbounded) behavior. A timed-out loader returns `None`
        (no cache write). Exceptions from `db_loader` are
        re-raised unchanged.

        M5.7: `negative_cache_ttl_millis` writes a short-TTL
        negative marker on TIMEOUT so subsequent callers within
        the window return `None` without re-invoking the loader.
        """
        return self._stampede_load(
            key, clazz, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    def get_with_lock_typed(
        self,
        key: str,
        reference: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """防缓存击穿：结构化对象（运行时类型版本）。

        与 ``get_with_lock`` 行为一致，仅参数 ``reference`` 表达的是
        运行时类型（替代 Java ``TypeReference<T>`` — Python 保留泛型
        信息，裸 ``type[T]`` 即可）。

        Args:
            key: 缓存键
            reference: 运行时解析的目标类型
            timeout_millis: 缓存 TTL（毫秒）
            db_loader: 回源加载器
            loader_timeout_millis: 可选 — M5.1：`db_loader` 的
                毫秒级超时。详见 `get_with_lock` 文档。
            negative_cache_ttl_millis: 可选 — M5.7：超时负缓存
                TTL；详见 `get_with_lock` 文档。

        Returns:
            缓存值；未命中且加载失败或超时时为 ``None``；命中负缓存
            标记时同样为 ``None``。
        """
        return self._stampede_load(
            key, reference, timeout_millis, db_loader,
            wait_budget_millis=int(timeout_millis),
            loader_timeout_millis=loader_timeout_millis,
            negative_cache_ttl_millis=negative_cache_ttl_millis,
        )

    # ── Stampede-prevention shared helper (M4) ─────────────────────

    def _stampede_load(
        self,
        key: str,
        clazz: type,
        timeout_millis: int,
        db_loader: Callable[[], Any],
        *,
        wait_budget_millis: int,
        loader_timeout_millis: int | None = None,
        negative_cache_ttl_millis: int | None = None,
    ) -> Any:
        """Shared implementation for `get_with_lock` + `get_with_lock_typed`.

        Returns the cached value (on hit) or the loaded value
        (after a successful db_loader round-trip). Returns ``None``
        if the db_loader returned ``None``, timed out (M5.1), or if
        a competing stampede lock holder didn't publish within the
        wait budget.

        M5.7: on TIMEOUT, optionally writes a bytes sentinel to the
        key with `negative_cache_ttl_millis`; subsequent callers
        within the window return ``None`` without re-invoking the
        loader. Only fires on TIMEOUT, never on a natural ``None``
        from the loader. M5.7 detection runs BEFORE the typed
        `get()` so a non-`str` `clazz` doesn't blow up trying to
        decode the sentinel bytes (e.g. `dict` would attempt a
        JSON parse and raise `SerializationError`).
        """
        if timeout_millis <= 0:
            raise ValueError("timeout_millis must be > 0")
        if db_loader is None:
            raise ValueError("db_loader is required")
        if loader_timeout_millis is not None and loader_timeout_millis <= 0:
            raise ValueError("loader_timeout_millis must be > 0 (or None)")
        if negative_cache_ttl_millis is not None and negative_cache_ttl_millis <= 0:
            raise ValueError(
                "negative_cache_ttl_millis must be > 0 (or None)"
            )

        # 1. Fast path. M5.7: detect the negative marker via a
        #    RAW GET BEFORE the typed `get(...)` — the sentinel
        #    bytes are not valid JSON and would raise
        #    `SerializationError` when decoded through `dict`.
        raw_peek = self._peek_raw(key)
        if raw_peek is not None:
            if _is_negative(raw_peek):
                return None
            return self.get(key, clazz)

        # 2. Cache miss: try to acquire the per-key stampede lock.
        request_id = uuid.uuid4().hex
        lock_key = _make_stampede_lock_key(self._backend, key)
        client = self._backend.raw_client()
        if not _stampede_acquire(client, lock_key, request_id, timeout_millis):
            published = self._wait_for_publication(
                key, clazz, wait_budget_millis=wait_budget_millis
            )
            if _is_negative(self._peek_raw(key)):
                return None
            return published

        try:
            # 3. We hold the stampede lock — re-check the cache
            #    (raw peek first to avoid JSON-decoding the sentinel).
            raw_peek = self._peek_raw(key)
            if raw_peek is not None:
                if _is_negative(raw_peek):
                    return None
                return self.get(key, clazz)
            # 4. Still missing → invoke the db_loader, optionally
            #    with a timeout. `_call_db_loader_with_timeout_ex`
            #    returns `(value, timed_out)`; we use the flag to
            #    decide whether to write a negative-cache marker
            #    (M5.7). The typed read (for `get_with_lock_typed`)
            #    happens AFTER this returns, in-process and bounded.
            value, was_timed_out = _call_db_loader_with_timeout_ex(
                db_loader, loader_timeout_millis
            )
            if value is None:
                # M5.7: TIMEOUT → write the negative-cache marker
                # via set_with_ttl. On a natural `None` we
                # deliberately do NOT write the marker — the
                # loader's "no value" answer should be re-attempted
                # on the next call.
                if (
                    was_timed_out
                    and negative_cache_ttl_millis is not None
                    and negative_cache_ttl_millis > 0
                ):
                    try:
                        self.set_with_ttl(
                            key, _NEGATIVE_SENTINEL,
                            int(negative_cache_ttl_millis),
                        )
                    except Exception:
                        pass
                return None
            # 5. Publish: caller-supplied TTL verbatim (no anti-
            #    avalanche offset; the `*_with_lock` path is the
            #    canonical write path).
            self.set_with_ttl(key, value, timeout_millis)
            return value
        finally:
            try:
                _stampede_release(client, lock_key, request_id)
            except Exception:
                # Release failures are non-fatal: the lock will
                # expire on its own via the PX TTL.
                pass

    def _peek_raw(self, key: str) -> bytes | None:
        """GET raw bytes for `key`, or `None` if absent.

        Used only by the M5.7 negative-cache detect path; lets us
        see the on-the-wire bytes without going through the typed
        `decode_value` round-trip (which would convert the sentinel
        into a benign str).
        """
        return self._backend.raw_client().get(self._k(key))

    def _wait_for_publication(
        self, key: str, clazz: type, *, wait_budget_millis: int
    ) -> Any:
        """Poll the cache for up to `wait_budget_millis` (50ms cadence).

        Returns the published value, or ``None`` if no one published
        within the budget. A published negative-cache marker is
        surfaced as ``None`` (the lock-holder wrote it on a
        `loader_timeout_millis` timeout — callers should treat it
        as a clean miss-and-don't-retry-for-the-TTL-window).
        """
        deadline = time.monotonic() + (wait_budget_millis / 1000.0)
        poll_interval_seconds = 0.05
        while time.monotonic() < deadline:
            time.sleep(poll_interval_seconds)
            cached = self.get(key, clazz)
            if cached is not None:
                if _is_negative(self._peek_raw(key)):
                    return None
                return cached
        return None


__all__ = ["RedisStructManager"]
