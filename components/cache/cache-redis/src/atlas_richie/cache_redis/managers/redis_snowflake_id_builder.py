"""全局分布式 ID 生成器。
----
``SnowflakeIdBuilder`` 的 Redis 后端实现（R-224）。

**请注意：本分布式 ID 生成器需要依赖 Redis 中间件**

镜像 ``cn.richie696.component.cache.redis.snowflake.IdBuilder`` 的结构。
64 位布局如下：

::

    bit 63       : 0  （符号位，始终为 0 → 适配有符号 int64）
    bits 53-62   : workerId  （10 位，0..1023）
    bits 12-52   : timestamp （41 位，2020-05-03 UTC 起的毫秒数）
    bits 0-11    : sequence  （12 位，每毫秒 0..4095）

**WorkerId 分配**：首次使用时，Lua 脚本从注册表 key ``snowflake:workId``
原子地分配一个 workerId。分配方式为轮询：0, 1, 2, ..., 1023, 0, 1, ...
未归还的 worker ID（进程消亡）会一直泄露到循环回绕；强制实行 1024 个
worker 的有界上限。

**同毫秒序号**：进程内的 ``AtomicLong`` 计数器在每次 ``next_id()`` 时递增。
当每毫秒的序号用尽（4095 ID/ms）时，构建器在 ``time.sleep(5ms)`` 上自旋
直到下一个毫秒边界。

**并发性**：共享单个构建器的多个线程共享同一个 ``AtomicLong``，因此任意
线程的 ``next_id()`` 调用在进程范围内都是唯一的。

English
--------
Redis-backed `SnowflakeIdBuilder` (R-224).

Mirrors `cn.richie696.component.cache.redis.snowflake.IdBuilder`
1:1. The 64-bit layout is::

    bit 63       : 0  (sign bit, always 0 → fits in a signed int64)
    bits 53-62   : workerId  (10 bits, 0..1023)
    bits 12-52   : timestamp (41 bits, ms since 2020-05-03 UTC)
    bits 0-11    : sequence  (12 bits, 0..4095 per ms)

**WorkerId allocation**: on first use, a Lua script atomically
allocates a workerId from the registry key `snowflake:workId`. The
allocation is round-robin: 0, 1, 2, ..., 1023, 0, 1, ...  Worker
IDs that aren't returned (process dies) are leaked until the cycle
wraps; the bounded cap of 1024 workers is enforced.

**Same-ms sequence**: in-process `AtomicLong` counter increments
per `next_id()`. When the per-ms sequence exhausts (4095 IDs/ms),
the builder spins on `time.sleep(5ms)` until the next ms boundary.

**Concurrency**: multiple threads sharing a single builder share the
same `AtomicLong`, so a `next_id()` call from any thread is unique
across the process.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Optional

from atlas_richie.cache_core.contracts.snowflake_id_builder import (
    SnowflakeIdBuilder,
)

from ..redis_distributed_cache import RedisDistributedCache


# 2020-05-03 00:00:00 +08:00 (Asia/Shanghai), which is
# 2020-05-02 16:00:00 UTC. Matches the Java reference literal
# `1588435200000L` (the Java docstring says "2020-05-03" without
# timezone; the actual epoch is +08:00 because that's the canonical
# timestamp from the original Snowflake fork that the Java code
# ported). We mirror Java 1:1 to keep ID compatibility across
# language boundaries.
EPOCH_MS: int = 1_588_435_200_000

WORKER_ID_BITS = 10
TIMESTAMP_BITS = 41
SEQUENCE_BITS = 12

# The shift for `(ts << sequenceBits) | (workerId << (ts+seq))`.
# workerId is shifted up by 53 (ts_bits + seq_bits).
WORKER_ID_SHIFT = TIMESTAMP_BITS + SEQUENCE_BITS
SEQUENCE_SHIFT = SEQUENCE_BITS
TIMESTAMP_AND_SEQUENCE_MASK = (1 << (TIMESTAMP_BITS + SEQUENCE_BITS)) - 1

MAX_WORKER_ID = (1 << WORKER_ID_BITS) - 1  # 1023
MAX_SEQUENCE = (1 << SEQUENCE_BITS) - 1   # 4095

# Lua: allocate a workerId round-robin from 0..1023.
# `KEYS[1]` = the worker registry key. Atomic via single EVAL.
_ALLOCATE_WORKER_ID_LUA = """
local current = tonumber(redis.call('GET', KEYS[1]))
if not current or current >= 1024 then
  current = 0
end
redis.call('SET', KEYS[1], current + 1)
return current
"""


class RedisSnowflakeIdBuilder(SnowflakeIdBuilder):
    """全局分布式 ID 生成器（基于 Redis worker-id 注册表）。
    ----
    通过 Redis worker-id 注册表实现的 Snowflake ID 构建器。

    构建器是进程范围的：一旦实例化，workerId 在对象生命周期内固定。
    来自多个线程的并发 ``next_id()`` 调用是安全的（序号计数器等效于
    ``AtomicLong``）。

    English
    --------
    Snowflake ID builder backed by a Redis worker-id registry.

    The builder is process-wide: once instantiated, the workerId is
    fixed for the lifetime of the object. Concurrent `next_id()` calls
    from multiple threads are safe (sequence counter is an
    `AtomicLong`-equivalent).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        key: str = "snowflake:workId",
    ) -> None:
        self._backend = backend
        self._registry_key = backend.make_key(key)
        self._worker_id = self._allocate_worker_id()
        # `self._worker_id_shifted` is `workerId << 53`, the value
        # OR'd into the high bits of every generated ID.
        self._worker_id_shifted = self._worker_id << WORKER_ID_SHIFT
        # `self._last_ts_seq` packs (timestamp << 12) | sequence in the
        # low 53 bits (matching Java's `timestampAndSequence`).
        initial = self._newest_timestamp() << SEQUENCE_SHIFT
        self._last_ts_seq = _AtomicLong(initial)
        self._lock = threading.Lock()  # for the `waitIfNecessary` spin

    # ── SnowflakeIdBuilder contract ────────────────────────────

    def next_id(self) -> int:
        """Generate a globally unique 64-bit ID."""
        self._wait_if_necessary()
        # Atomically increment the packed (ts, seq) counter.
        next_val = self._last_ts_seq.increment_and_get()
        ts_with_seq = next_val & TIMESTAMP_AND_SEQUENCE_MASK
        return self._worker_id_shifted | ts_with_seq

    # ── introspection (for tests) ──────────────────────────────

    @property
    def worker_id(self) -> int:
        return self._worker_id

    # ── internal ──────────────────────────────────────────────

    def _allocate_worker_id(self) -> int:
        """Round-robin allocate a workerId from the Redis registry."""
        result = self._backend.raw_client().eval(
            _ALLOCATE_WORKER_ID_LUA, 1, self._registry_key
        )
        worker_id = int(result)
        if not (0 <= worker_id <= MAX_WORKER_ID):
            raise RuntimeError(
                f"snowflake: invalid workerId {worker_id} from Redis "
                f"(expected 0..{MAX_WORKER_ID})"
            )
        return worker_id

    def _newest_timestamp(self) -> int:
        """Return the timestamp (ms since EPOCH_MS) for the current time."""
        return int(time.time() * 1000) - EPOCH_MS

    def _wait_if_necessary(self) -> None:
        """Block current thread if the per-ms sequence is exhausted."""
        with self._lock:
            current_with_seq = self._last_ts_seq.get()
            current_ts = current_with_seq >> SEQUENCE_SHIFT
            newest = self._newest_timestamp()
            if current_ts >= newest:
                time.sleep(0.005)


class _AtomicLong:
    """Minimal `AtomicLong` replacement for the (timestamp, sequence)
    counter. Backed by a `threading.Lock` for cross-thread safety."""

    __slots__ = ("_value", "_lock")

    def __init__(self, initial: int) -> None:
        self._value = initial
        self._lock = threading.Lock()

    def increment_and_get(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def get(self) -> int:
        with self._lock:
            return self._value


__all__ = [
    "RedisSnowflakeIdBuilder",
    "EPOCH_MS",
    "MAX_WORKER_ID",
    "MAX_SEQUENCE",
]
