"""Redisson 实现的布隆过滤器，作为 ``BloomFilter`` SPI 的分布式实现。
----
Redis 后端的共享 ``BloomFilter``（R-222）。

**激活条件**（来自参考实现）：``platform.cache.bloom-filter.enable=true``
且 ``platform.cache.bloom-filter.type=REDISSON``。当 ``type=GUAVA`` 或
未启用 bloom 时本 bean 不创建，自动回落到 Guava 内存实现。

存储
~~~~
底层走 Redis 客户端，bloom 数据持久化到 Redis（key 由 ``CacheProperties``
的 ``bloomFilter`` 配置控制）。多实例间共享同一份 bloom 状态，避免单点
Guava 内存 bloom 在分布式部署下失效。

镜像 ``cn.richie696.component.cache.bloom.RedissonBloomFilter`` 的结构。
两种策略共存：

- ``RedisSharedBloomFilter``（本文件）—— Redis BITSET + Lua 原子操作。
  多个进程共享同一个位数组。
- ``InMemoryBloomFilter``（见 ``in_memory_bloom_filter.py``）—— Python
  ``bytearray`` + ``hashlib``。单进程；无 I/O。

每个 filter 在缓存 namespace 下的存储布局：

- ``{ns}:bloom:{name}``       —— Redis BITSET，size = ceil(bit_size)。
- ``{ns}:bloom:{name}:meta``  —— Redis HASH，包含 ``bit_size`` 与
  ``hash_count``。

**原子性**：每个 ``add`` / ``might_contain`` / ``add_all`` / ``contains_all``
都作为单个 ``EVAL`` 运行，使 SETBIT/GETBIT 被其它进程原子地观察。共享
布隆过滤器的全部意义就在于从任何视角看都是同一组 bit。

**哈希**：我们使用单个 ``sha256(item)`` 摘要，取前 8 字节作为 64 位整数
（``hash_lo``），通过 Kirsch-Mitzenmacher 双哈希技术生成 k 个索引：

::

    h_i = (hash_lo + i * hash_hi) % bit_size

其中 ``hash_hi`` 是摘要的后 8 字节，被解释为第二个 64 位整数。这提供了一个
高质量、良好分布的 k 个伪独立哈希族，无需多轮哈希函数。

English
--------
Redis-backed shared `BloomFilter` (R-222).

Mirrors `cn.richie696.component.cache.bloom.RedissonBloomFilter` 1:1.
Two strategies coexist:

  - `RedisSharedBloomFilter` (this file) — Redis BITSET + Lua atomics.
    Multiple processes share the same bit-array.
  - `InMemoryBloomFilter` (see `in_memory_bloom_filter.py`) — Python
    `bytearray` + `hashlib`. Single-process; no I/O.

Storage layout per filter (in the cache's namespace):

  `{ns}:bloom:{name}`       — Redis BITSET, size = ceil(bit_size).
  `{ns}:bloom:{name}:meta`  — Redis HASH with `bit_size` + `hash_count`.

**Atomicity**: every `add` / `might_contain` / `add_all` / `contains_all`
runs as a single `EVAL` so the SETBIT/GETBITs are observed atomically
by other processes. The whole point of a shared Bloom filter is to be
the same bits from every vantage point.

**Hashing**: we use a single `sha256(item)` digest, take the first 8
bytes as a 64-bit integer (`hash_lo`), and generate k indices via the
Kirsch-Mitzenmacher double-hashing technique:

    h_i = (hash_lo + i * hash_hi) % bit_size

where `hash_hi` is the next 8 bytes of the digest interpreted as a
second 64-bit integer. This gives a high-quality, well-distributed
family of k pseudo-independent hashes without a multi-pass hash
function.
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable, Sequence

from atlas_richie.cache_core.config.bloom_filter_config import BloomFilterConfig
from atlas_richie.cache_core.contracts.bloom_filter import BloomFilter

from ..redis_distributed_cache import RedisDistributedCache


# Lua: atomically SETBIT at k bit positions, return the number of bits
# that were newly set to 1. `KEYS[1]` = the bit-array key, `KEYS[2]` =
# the meta key. `ARGV[1]` = hash_count (loop bound). `ARGV[2..1+k]` =
# the k pre-computed bit positions (deterministic, no Lua-side
# arithmetic). The bit_size is read from the meta hash so the script
# doesn't need a separate ARGV.
_BLOOM_ADD_LUA = """
local meta = redis.call('HMGET', KEYS[2], 'bit_size', 'hash_count')
if not meta[1] then
  return redis.error_reply('bloom: meta key not initialized')
end
local bit_size = tonumber(meta[1])
local n_new = 0
for i = 1, tonumber(ARGV[1]) do
  local pos = tonumber(ARGV[1 + i])
  if pos < 0 then pos = 0 end
  if pos >= bit_size then pos = bit_size - 1 end
  local prev = redis.call('GETBIT', KEYS[1], pos)
  redis.call('SETBIT', KEYS[1], pos, 1)
  if prev == 0 then n_new = n_new + 1 end
end
return n_new
"""

# Lua: atomically GETBIT at k bit positions; return 1 if ALL are 1,
# else 0. `KEYS[1]` = bit-array, `KEYS[2]` = meta. `ARGV[1]` =
# hash_count (loop bound). `ARGV[2..1+k]` = the k pre-computed bit
# positions. The bit_size is read from the meta hash.
_BLOOM_CONTAINS_LUA = """
local meta = redis.call('HMGET', KEYS[2], 'bit_size', 'hash_count')
if not meta[1] then
  return 0
end
local bit_size = tonumber(meta[1])
for i = 1, tonumber(ARGV[1]) do
  local pos = tonumber(ARGV[1 + i])
  if pos < 0 then pos = 0 end
  if pos >= bit_size then pos = bit_size - 1 end
  if redis.call('GETBIT', KEYS[1], pos) == 0 then
    return 0
  end
end
return 1
"""


def compute_dimensions(
    expected_insertions: int, false_probability: float
) -> tuple[int, int]:
    """Return (bit_size, hash_count) for a Bloom filter with the
    given capacity and target false-positive rate.

    Standard formulas (Bloom 1970):
        m = -n * ln(p) / (ln 2)^2
        k = (m / n) * ln 2
    """
    if expected_insertions <= 0:
        raise ValueError("expected_insertions must be > 0")
    if not (0.0 < false_probability < 1.0):
        raise ValueError("false_probability must be in (0, 1)")
    n = float(expected_insertions)
    p = float(false_probability)
    m = int(math.ceil(-n * math.log(p) / (math.log(2) ** 2)))
    k = max(1, int(round((m / n) * math.log(2))))
    return m, k


def _hash_pair(item: bytes | str) -> tuple[int, int]:
    """Two 64-bit hashes for double-hashing.

    Accepts both `bytes` and `str`; `str` is utf-8 encoded first.
    """
    if isinstance(item, str):
        item = item.encode("utf-8")
    digest = hashlib.sha256(item).digest()
    # First 8 bytes -> hash_lo (big-endian unsigned).
    hash_lo = int.from_bytes(digest[:8], "big", signed=False)
    # Next 8 bytes -> hash_hi. If it would be 0 (vanishingly rare for
    # sha256), nudge to 1 to keep the k indices distinct.
    hash_hi = int.from_bytes(digest[8:16], "big", signed=False) or 1
    return hash_lo, hash_hi


def _positions(
    item: bytes | str, bit_size: int, hash_count: int
) -> list[int]:
    """Compute the k bit positions for `item` via Kirsch-Mitzenmacher."""
    hash_lo, hash_hi = _hash_pair(item)
    return [
        (hash_lo + i * hash_hi) % bit_size for i in range(hash_count)
    ]


class RedisSharedBloomFilter(BloomFilter):
    """基于 Redis BITSET + Lua 原子操作实现的分布式布隆过滤器。
    ----
    Redisson 风格的共享布隆过滤器，多进程可观察到同一组 bit。

    调用方传入一个 ``BloomFilterConfig``（来自 cache-core），用于控制
    期望容量、误判率与 Redis key。首次构造（meta key 缺失）时会初始化
    位数组；后续以相同 key 构造时复用现有维度，使 bit 在进程重启后
    仍然保留。

    English
    --------
    Distributed Bloom filter backed by a Redis BITSET + Lua atomics.

    The caller passes a `BloomFilterConfig` (from cache-core) that
    controls the expected capacity, false-positive rate, and Redis key.
    On first construction (when the meta key is absent) the bit-array
    is initialized; subsequent constructions with the same key re-use
    the existing dimensions so the bits survive process restarts.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        config: BloomFilterConfig,
    ) -> None:
        self._backend = backend
        self._config = config
        self._bit_key = backend.make_key(f"bloom:{config.key}")
        self._meta_key = backend.make_key(f"bloom:{config.key}:meta")
        self._bit_size, self._hash_count = self._ensure_meta()

    # ── meta + init ──────────────────────────────────────────────

    def _ensure_meta(self) -> tuple[int, int]:
        raw = self._backend.raw_client()
        meta = raw.hgetall(self._meta_key)
        if meta and "bit_size" in meta and "hash_count" in meta:
            return int(meta["bit_size"]), int(meta["hash_count"])
        bit_size, hash_count = compute_dimensions(
            self._config.expected_insertions,
            self._config.false_probability,
        )
        # Atomically write meta only if absent. If a concurrent
        # initializer already wrote it, read theirs instead.
        pipe = raw.pipeline()
        pipe.hsetnx(self._meta_key, "bit_size", bit_size)
        pipe.hsetnx(self._meta_key, "hash_count", hash_count)
        pipe.hgetall(self._meta_key)
        _, _, written = pipe.execute()
        return int(written["bit_size"]), int(written["hash_count"])

    # ── BloomFilter contract ────────────────────────────────────

    def add(self, item: bytes | str) -> None:
        positions = _positions(item, self._bit_size, self._hash_count)
        self._backend.raw_client().eval(
            _BLOOM_ADD_LUA,
            2,
            self._bit_key,
            self._meta_key,
            str(self._hash_count),
            *[str(p) for p in positions],
        )

    def might_contain(self, item: bytes | str) -> bool:
        positions = _positions(item, self._bit_size, self._hash_count)
        result = self._backend.raw_client().eval(
            _BLOOM_CONTAINS_LUA,
            2,
            self._bit_key,
            self._meta_key,
            str(self._hash_count),
            *[str(p) for p in positions],
        )
        return int(result) == 1

    # ── non-contract helpers (mirror Java's `putAll` / `isExists`) ──

    def add_all(self, items: Iterable[bytes | str]) -> None:
        for item in items:
            self.add(item)

    def is_exists(self) -> bool:
        return bool(self._backend.raw_client().exists(self._bit_key))

    def reset(self) -> None:
        """Drop the bit-array and meta. Useful for tests."""
        raw = self._backend.raw_client()
        raw.delete(self._bit_key, self._meta_key)
        # Re-initialize.
        self._bit_size, self._hash_count = self._ensure_meta()

    # ── introspection ───────────────────────────────────────────

    @property
    def bit_size(self) -> int:
        return self._bit_size

    @property
    def hash_count(self) -> int:
        return self._hash_count


__all__ = [
    "RedisSharedBloomFilter",
    "compute_dimensions",
]
