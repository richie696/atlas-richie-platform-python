"""Guava 实现的本地布隆过滤器，作为 ``BloomFilter`` SPI 的备选实现。
----
进程内 ``BloomFilter``（R-222）。

**激活条件**（来自参考实现）：``platform.cache.bloom-filter.enable=true``
且 ``platform.cache.bloom-filter.type=GUAVA``。

**注意**：本实现与 ``RedisSharedBloomFilter`` 并存；它使用与 Redis 端
相同的 SHA-256 双哈希，保证两者对相同 item 产生 bit-identical 位置
（便于跨后端行为对比测试）。

镜像 ``cn.richie696.component.cache.bloom.GuavaBloomFilter`` 的结构。
单进程；使用 Python ``bytearray`` 作为位数组。

本实现刻意保持极简 —— 不使用 ``RLock``（Python 的 GIL 使单 bytearray
更新在用例上实际是原子的）、不使用 ``__slots__``（用户可能希望子类化）。

English
--------
In-memory `BloomFilter` (R-222).

Mirrors `cn.richie696.component.cache.bloom.GuavaBloomFilter` 1:1.
Single-process; uses a Python `bytearray` as the bit array and the
same SHA-256 double-hashing as `RedisSharedBloomFilter` so the two
backends produce bit-identical positions for the same item (useful
for tests that compare behaviour).

This implementation is intentionally minimal — no `RLock` (Python's
GIL makes a single-bytearray update effectively atomic for our
use-case), no `__slots__` (the user might want to subclass).
"""

from __future__ import annotations

import hashlib
import math
from typing import Iterable

from atlas_richie.cache_core.config.bloom_filter_config import BloomFilterConfig
from atlas_richie.cache_core.contracts.bloom_filter import BloomFilter

from .redis_bloom_filter import _hash_pair  # reuse Kirsch-Mitzenmacher


def _compute_dimensions(
    expected_insertions: int, false_probability: float
) -> tuple[int, int]:
    if expected_insertions <= 0:
        raise ValueError("expected_insertions must be > 0")
    if not (0.0 < false_probability < 1.0):
        raise ValueError("false_probability must be in (0, 1)")
    n = float(expected_insertions)
    p = float(false_probability)
    m = int(math.ceil(-n * math.log(p) / (math.log(2) ** 2)))
    k = max(1, int(round((m / n) * math.log(2))))
    return m, k


def _positions(item: bytes | str, bit_size: int, hash_count: int) -> list[int]:
    hash_lo, hash_hi = _hash_pair(item)
    return [(hash_lo + i * hash_hi) % bit_size for i in range(hash_count)]


class InMemoryBloomFilter(BloomFilter):
    """进程级布隆过滤器，跨进程不共享。
    ----
    Guava 风格的本地布隆过滤器，使用 Python ``bytearray`` 与 SHA-256
    双哈希实现。

    English
    --------
    Process-local Bloom filter. Not shared across processes.
    """

    def __init__(
        self,
        expected_insertions: int = 1_000_000,
        false_probability: float = 0.001,
    ) -> None:
        bit_size, hash_count = _compute_dimensions(
            expected_insertions, false_probability
        )
        self._bit_size = bit_size
        self._hash_count = hash_count
        self._bits = bytearray((bit_size + 7) // 8)
        self._count = 0

    @classmethod
    def from_config(
        cls, config: BloomFilterConfig
    ) -> "InMemoryBloomFilter":
        return cls(
            expected_insertions=config.expected_insertions,
            false_probability=config.false_probability,
        )

    # ── BloomFilter contract ────────────────────────────────────

    def add(self, item: bytes | str) -> None:
        for pos in _positions(item, self._bit_size, self._hash_count):
            byte_idx, bit_idx = divmod(pos, 8)
            mask = 1 << (7 - (bit_idx % 8))
            if not (self._bits[byte_idx] & mask):
                self._bits[byte_idx] |= mask
                self._count += 1

    def might_contain(self, item: bytes | str) -> bool:
        for pos in _positions(item, self._bit_size, self._hash_count):
            byte_idx, bit_idx = divmod(pos, 8)
            mask = 1 << (7 - (bit_idx % 8))
            if not (self._bits[byte_idx] & mask):
                return False
        return True

    # ── non-contract helpers ────────────────────────────────────

    def add_all(self, items: Iterable[bytes | str]) -> None:
        for item in items:
            self.add(item)

    def count(self) -> int:
        """Approximate count of items added (lower bound, since
        duplicate adds don't bump the count)."""
        return self._count

    def bit_size(self) -> int:
        return self._bit_size

    def hash_count(self) -> int:
        return self._hash_count

    def reset(self) -> None:
        for i in range(len(self._bits)):
            self._bits[i] = 0
        self._count = 0


__all__ = ["InMemoryBloomFilter"]
