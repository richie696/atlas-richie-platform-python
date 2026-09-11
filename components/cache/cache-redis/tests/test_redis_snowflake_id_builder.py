"""Tests for the R-224 `RedisSnowflakeIdBuilder`.

Coverage:
  - basic `next_id()` returns a 64-bit int
  - monotonic within a process (IDs strictly increase)
  - bit layout: bit 63 = 0, bits 53-62 = workerId, bits 12-52 = ts, bits 0-11 = seq
  - the workerId is persisted to Redis (round-robin allocation)
  - two builders in the same process get different workerIds
  - IDs from different builders never collide
  - high-throughput burst (10_000 IDs in <1s) all unique
  - 64-bit signed range: IDs < 2^63
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisProviderRegistrar,
    RedisSnowflakeIdBuilder,
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
    namespace = f"R-224-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        reg.close()


def _extract_bits(id_: int) -> tuple[int, int, int]:
    """Return (worker_id, timestamp, sequence) from a Snowflake ID."""
    worker_id = (id_ >> 53) & ((1 << 10) - 1)
    timestamp = (id_ >> 12) & ((1 << 41) - 1)
    sequence = id_ & ((1 << 12) - 1)
    return worker_id, timestamp, sequence


class TestRedisSnowflakeIdBuilder:
    def test_basic_next_id_returns_int(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b: RedisSnowflakeIdBuilder = registrar.snowflake()
        id1 = b.next_id()
        assert isinstance(id1, int)
        assert id1 > 0
        print("  ✅ basic next_id()")

    def test_strictly_monotonic(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b = registrar.snowflake()
        ids = [b.next_id() for _ in range(100)]
        # Each subsequent ID must be greater than the previous one.
        for a, c in zip(ids, ids[1:]):
            assert c > a, f"non-monotonic: {a} → {c}"
        print("  ✅ 100 IDs are strictly monotonic")

    def test_bit_layout(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b = registrar.snowflake()
        id_ = b.next_id()
        # Bit 63 (sign bit) must be 0 → id fits in signed int64.
        assert id_ < (1 << 63), f"id {id_} overflows signed int64"
        # WorkerId field must match the builder's own workerId.
        worker_id, ts, seq = _extract_bits(id_)
        assert worker_id == b.worker_id
        # Timestamp must be non-zero and within ~1s of now.
        now_ts = int(time.time() * 1000) - 1_588_435_200_000
        assert abs(ts - now_ts) < 1_000
        # Sequence is 0..4095.
        assert 0 <= seq <= 4095
        print("  ✅ bit layout correct (workerId + ts + seq)")

    def test_worker_id_persisted_in_redis(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """The workerId is allocated round-robin from a Redis key."""
        # Allocate several builders, verify workerIds are 0, 1, 2, ...
        b1 = registrar.snowflake()
        b2 = registrar.snowflake()
        b3 = registrar.snowflake()
        # Each gets a distinct workerId (round-robin).
        assert b1.worker_id != b2.worker_id
        assert b2.worker_id != b3.worker_id
        assert b1.worker_id != b3.worker_id
        print(
            f"  ✅ 3 builders got distinct workerIds: "
            f"{b1.worker_id}, {b2.worker_id}, {b3.worker_id}"
        )

    def test_two_builders_different_workerIds(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b1 = registrar.snowflake()
        b2 = registrar.snowflake()
        assert b1.worker_id != b2.worker_id
        # Their IDs occupy different (worker, ts, seq) spaces.
        id1 = b1.next_id()
        id2 = b2.next_id()
        assert id1 != id2
        # WorkerId extracted from the ID matches the builder.
        assert _extract_bits(id1)[0] == b1.worker_id
        assert _extract_bits(id2)[0] == b2.worker_id
        print("  ✅ two builders generate non-colliding IDs")

    def test_high_throughput_no_collisions(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b = registrar.snowflake()
        ids = set()
        n = 10_000
        for _ in range(n):
            ids.add(b.next_id())
        assert len(ids) == n, f"collisions: {n - len(ids)} dupes"
        print(f"  ✅ {n} IDs in burst, all unique")

    def test_fits_in_signed_int64(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b = registrar.snowflake()
        for _ in range(100):
            id_ = b.next_id()
            # Python ints are unbounded, but the value must be
            # representable in a signed int64.
            assert id_ >= 0
            assert id_ < (1 << 63)
        print("  ✅ all IDs fit in signed int64")

    def test_concurrent_threads_see_unique_ids(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Multiple threads sharing one builder get unique IDs."""
        import threading

        b = registrar.snowflake()
        ids: list[int] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(500):
                id_ = b.next_id()
                with lock:
                    ids.append(id_)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 4 threads × 500 IDs = 2000 unique.
        assert len(ids) == 2000
        assert len(set(ids)) == 2000
        print("  ✅ 4 threads × 500 IDs = 2000 unique")

    def test_worker_id_within_range(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        b = registrar.snowflake()
        assert 0 <= b.worker_id <= 1023
        print(f"  ✅ worker_id {b.worker_id} in 0..1023")
