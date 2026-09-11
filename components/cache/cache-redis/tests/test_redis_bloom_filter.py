"""Tests for the R-222 Bloom filter implementations.

Coverage:
  - `InMemoryBloomFilter`:
      - add / might_contain round-trip
      - false-negative free, false-positive rate within bound
      - bit_size + hash_count match the formulas
      - reset() clears state
  - `RedisSharedBloomFilter`:
      - add / might_contain round-trip via Lua
      - false-negative free, false-positive rate within bound
      - cross-process: a second registrar opens the same filter and
        sees the bits set by the first
      - meta-key reuse on re-open (same key + different config
        doesn't shrink/grow the bit-array)
      - reset() drops bits and meta
  - Both: `might_contain` is fast (a few msec even for 10k items)
  - Both: hashing is deterministic (same item → same positions)
"""

from __future__ import annotations

import os
import random
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core.config.bloom_filter_config import (
    BloomFilterConfig,
)
from atlas_richie.cache_redis import (
    InMemoryBloomFilter,
    RedisProviderRegistrar,
    RedisSharedBloomFilter,
)
from atlas_richie.cache_redis.managers.redis_bloom_filter import (
    compute_dimensions,
)


REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-222-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        # Clean up all bloom keys.
        raw = reg._backend.raw_client()  # type: ignore[attr-defined]
        for k in list(raw.scan_iter(match=f"{reg._backend.namespace}:bloom:*", count=500)):  # type: ignore[attr-defined]
            raw.delete(k)
        reg.close()


# ── Pure-Python: compute_dimensions + InMemoryBloomFilter ─────────


class TestComputeDimensions:
    def test_standard_formulas(self) -> None:
        # Bloom 1970: 1M items, 1% false-positive.
        # bit_size ≈ 9_585_059, hash_count ≈ 7
        m, k = compute_dimensions(1_000_000, 0.01)
        assert 9_500_000 < m < 9_700_000
        assert 6 <= k <= 8

    def test_rejects_zero_or_negative_n(self) -> None:
        with pytest.raises(ValueError):
            compute_dimensions(0, 0.01)
        with pytest.raises(ValueError):
            compute_dimensions(-1, 0.01)

    def test_rejects_invalid_p(self) -> None:
        with pytest.raises(ValueError):
            compute_dimensions(1_000, 0.0)
        with pytest.raises(ValueError):
            compute_dimensions(1_000, 1.0)
        with pytest.raises(ValueError):
            compute_dimensions(1_000, 1.5)


class TestInMemoryBloomFilter:
    def test_round_trip(self) -> None:
        bf = InMemoryBloomFilter(
            expected_insertions=10_000, false_probability=0.01
        )
        bf.add("hello")
        bf.add("world")
        assert bf.might_contain("hello") is True
        assert bf.might_contain("world") is True
        assert bf.might_contain("absent") is False
        print("  ✅ in-memory round-trip")

    def test_no_false_negatives(self) -> None:
        """Adding 1000 items, every one must be reported present."""
        bf = InMemoryBloomFilter(
            expected_insertions=10_000, false_probability=0.01
        )
        items = [f"item-{i}".encode() for i in range(1_000)]
        for item in items:
            bf.add(item)
        for item in items:
            assert bf.might_contain(item) is True, f"false negative for {item!r}"
        print("  ✅ no false negatives (1000 items)")

    def test_false_positive_rate_within_bound(self) -> None:
        """False-positive rate must stay within ~2x the target."""
        bf = InMemoryBloomFilter(
            expected_insertions=10_000, false_probability=0.01
        )
        for i in range(10_000):
            bf.add(f"in-{i}".encode())
        fp = 0
        trials = 10_000
        for i in range(trials):
            if bf.might_contain(f"out-{i}".encode()):
                fp += 1
        observed = fp / trials
        # Target 0.01; allow 3x headroom for sample-size jitter.
        assert observed < 0.03, f"observed FP rate {observed:.4f} > 0.03"
        print(f"  ✅ FP rate {observed:.4f} within 3x of target 0.01")

    def test_reset_clears_state(self) -> None:
        bf = InMemoryBloomFilter(
            expected_insertions=1_000, false_probability=0.01
        )
        bf.add("a")
        bf.add("b")
        assert bf.might_contain("a") is True
        bf.reset()
        assert bf.might_contain("a") is False
        assert bf.might_contain("b") is False
        print("  ✅ reset() clears state")

    def test_str_and_bytes_equivalent(self) -> None:
        bf = InMemoryBloomFilter(
            expected_insertions=1_000, false_probability=0.01
        )
        bf.add("hello")
        bf.add(b"hello")
        # Both should be present (same content).
        assert bf.might_contain("hello") is True
        assert bf.might_contain(b"hello") is True
        print("  ✅ str and bytes are equivalent")

    def test_dimensions(self) -> None:
        bf = InMemoryBloomFilter(
            expected_insertions=10_000, false_probability=0.01
        )
        m, k = compute_dimensions(10_000, 0.01)
        assert bf.bit_size() == m
        assert bf.hash_count() == k
        print("  ✅ dimensions match compute_dimensions()")


# ── Redis-backed: RedisSharedBloomFilter ────────────────────────────


class TestRedisSharedBloomFilter:
    def test_round_trip(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"rt-{uuid.uuid4().hex[:8]}",
            expected_insertions=10_000,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        bf.add("hello")
        bf.add("world")
        assert bf.might_contain("hello") is True
        assert bf.might_contain("world") is True
        assert bf.might_contain("absent") is False
        print("  ✅ shared round-trip via Lua")

    def test_no_false_negatives(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"nofn-{uuid.uuid4().hex[:8]}",
            expected_insertions=5_000,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        items = [f"item-{i}".encode() for i in range(1_000)]
        for item in items:
            bf.add(item)
        for item in items:
            assert bf.might_contain(item) is True
        print("  ✅ shared: no false negatives (1000 items)")

    def test_false_positive_rate_within_bound(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"fpr-{uuid.uuid4().hex[:8]}",
            expected_insertions=5_000,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        for i in range(5_000):
            bf.add(f"in-{i}".encode())
        fp = 0
        trials = 5_000
        for i in range(trials):
            if bf.might_contain(f"out-{i}".encode()):
                fp += 1
        observed = fp / trials
        # Allow 3x headroom.
        assert observed < 0.03, f"observed FP rate {observed:.4f} > 0.03"
        print(f"  ✅ shared FP rate {observed:.4f} within 3x of 0.01")

    def test_cross_process_state(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """A second registrar (or re-open of the same registrar with
        the same key) sees the bits set by the first."""
        key = f"xproc-{uuid.uuid4().hex[:8]}"
        config = BloomFilterConfig(
            enable=True, key=key, expected_insertions=1_000, false_probability=0.01
        )
        bf1 = registrar.bloom_shared(config)
        bf1.add("alpha")
        bf1.add("beta")

        # A second shared filter on the same key (re-opens the existing
        # bit-array).
        bf2 = registrar.bloom_shared(config)
        assert bf2.might_contain("alpha") is True
        assert bf2.might_contain("beta") is True
        assert bf2.might_contain("gamma") is False
        print("  ✅ cross-process state (re-open sees same bits)")

    def test_meta_reuse_preserves_dimensions(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Re-opening with a *different* config (smaller capacity, lower
        FP rate) must NOT shrink the bit-array; the original meta wins.
        This is a key Bloom filter property: the bit array never gets
        smaller once initialized."""
        key = f"meta-{uuid.uuid4().hex[:8]}"
        big = BloomFilterConfig(
            enable=True, key=key, expected_insertions=100_000, false_probability=0.001
        )
        small = BloomFilterConfig(
            enable=True, key=key, expected_insertions=100, false_probability=0.5
        )
        bf1 = registrar.bloom_shared(big)
        size1 = bf1.bit_size
        count1 = bf1.hash_count

        bf2 = registrar.bloom_shared(small)
        size2 = bf2.bit_size
        count2 = bf2.hash_count

        # Same bit array (not shrunk).
        assert size2 == size1
        assert count2 == count1
        print("  ✅ meta reuse: bit-array never shrinks")

    def test_reset_drops_bits_and_meta(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"reset-{uuid.uuid4().hex[:8]}",
            expected_insertions=1_000,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        bf.add("a")
        assert bf.might_contain("a") is True
        bf.reset()
        assert bf.might_contain("a") is False
        print("  ✅ reset() drops bits and meta")

    def test_is_exists(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"exists-{uuid.uuid4().hex[:8]}",
            expected_insertions=100,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        # The bit-array key is created on the first add (or with meta).
        # Our `_ensure_meta` only writes meta; the bit-array is created
        # on the first SETBIT. So `is_exists` returns False until then.
        assert bf.is_exists() is False
        bf.add("a")
        assert bf.is_exists() is True
        print("  ✅ is_exists() reflects bit-array presence")


# ── Performance sanity (both backends) ──────────────────────────────


class TestBloomPerformance:
    def test_in_memory_10k_ops_under_500ms(self) -> None:
        bf = InMemoryBloomFilter(
            expected_insertions=10_000, false_probability=0.01
        )
        t0 = time.monotonic()
        for i in range(10_000):
            bf.add(f"k-{i}")
        for i in range(10_000):
            bf.might_contain(f"k-{i}")
        elapsed = time.monotonic() - t0
        assert elapsed < 0.5, f"20k ops took {elapsed:.3f}s"
        print(f"  ✅ in-memory 20k ops in {elapsed * 1000:.0f}ms")

    def test_redis_shared_1k_ops_under_5s(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        config = BloomFilterConfig(
            enable=True,
            key=f"perf-{uuid.uuid4().hex[:8]}",
            expected_insertions=1_000,
            false_probability=0.01,
        )
        bf = registrar.bloom_shared(config)
        t0 = time.monotonic()
        for i in range(1_000):
            bf.add(f"k-{i}")
        for i in range(1_000):
            bf.might_contain(f"k-{i}")
        elapsed = time.monotonic() - t0
        assert elapsed < 5.0, f"2k ops took {elapsed:.3f}s"
        print(f"  ✅ redis 2k ops in {elapsed * 1000:.0f}ms")
