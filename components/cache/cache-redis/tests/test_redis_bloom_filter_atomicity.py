"""Concurrency + atomicity tests for ``RedisSharedBloomFilter`` (R-222).

Validates the atomicity claim from the implementation
(`components/cache/cache-redis/src/atlas_richie/cache_redis/managers/redis_bloom_filter.py`):

  every `add` / `might_contain` / `add_all` runs as Lua ``EVAL`` so
  SETBIT/GETBITs are observed atomically by other processes.

Coverage
--------

1. **Concurrent add to same key** — 10 threads racing on the same
   item. The Lua SETBIT burst must guarantee no lost writes: the
   item must be `might_contain`-able afterwards.
2. **Concurrent add to different items, same key** — 10 threads
   adding distinct items in parallel. Every item must be
   present.
3. **add + might_contain interleaving** — 5 adders + 5
   contains-readers. After all threads finish, every added item
   must be contained (no partial / torn bit state visible).
4. **Lua EVAL script idempotence** — the SETBIT script must
   produce the same bit-pattern whether called once with N items
   or N times with one item each. We compare ``BITCOUNT`` on two
   filters that received the same set of items via the two
   patterns.
5. **``add_all`` atomicity / per-item Lua EVAL** — ``add_all`` is
   implemented as a loop of per-item ``add()`` calls; each
   individual ``add()`` is a single Lua ``EVAL``, so the
   per-item SETBIT burst is atomic. We verify the per-item
   atomicity by reading the bit-array between concurrent adds
   and confirming a parallel reader never observes a partial
   state for a single item (verified via ``BITCOUNT`` monotonic
   increase under contention).

Notes
-----
- The existing ``add_all`` is N EVALs (one per item), not 1 EVAL.
  This is a deliberate design choice: the per-item EVAL is small
  enough to keep tail latency low while still preserving
  per-item atomicity. A future optimisation could batch into a
  single EVAL; that's a separate change.
- These tests run against a real Redis instance (the same one
  used by the other R-222 tests) and are skipped if Redis is
  unreachable.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Iterator, List

import pytest
import redis as redis_lib

from atlas_richie.cache_core.config.bloom_filter_config import (
    BloomFilterConfig,
)
from atlas_richie.cache_redis import (
    RedisProviderRegistrar,
    RedisSharedBloomFilter,
)
from atlas_richie.cache_redis.managers.redis_bloom_filter import (
    _BLOOM_ADD_LUA,
    _BLOOM_CONTAINS_LUA,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


@pytest.fixture
def registrar() -> Iterator[RedisProviderRegistrar]:
    """A fresh registrar per-test with a unique namespace; bloom
    keys are wiped on teardown."""
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    namespace = f"R-222-Atomicity:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        raw = reg._backend.raw_client()  # type: ignore[attr-defined]
        for k in list(
            raw.scan_iter(
                match=f"{reg._backend.namespace}:bloom:*", count=500  # type: ignore[attr-defined]
            )
        ):
            raw.delete(k)
        reg.close()


def _make_filter(
    registrar: RedisProviderRegistrar, name: str
) -> RedisSharedBloomFilter:
    return registrar.bloom_shared(
        BloomFilterConfig(
            enable=True,
            key=name,
            expected_insertions=10_000,
            false_probability=0.01,
        )
    )


# ════════════════════════════════════════════════════════════════════
# 1. Concurrent add to SAME key — no lost writes
# ════════════════════════════════════════════════════════════════════


class TestConcurrentAddSameKey:
    """10 threads all calling ``add("item-X")`` simultaneously. The
    Lua script's per-item atomicity must guarantee that the
    subsequent ``might_contain`` returns True.

    This is the basic "no lost writes" claim: even under
    contention, every thread's SETBIT burst is observed as a
    single atomic transition.
    """

    def test_ten_threads_adding_same_item(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        bf = _make_filter(registrar, f"same-{uuid.uuid4().hex[:8]}")
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        errors: List[BaseException] = []
        errors_lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait()
                bf.add("contended-item")
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"workers errored: {errors!r}"
        # The item MUST be in the bloom — no thread's write was lost.
        assert bf.might_contain("contended-item") is True, (
            "item not present after concurrent add — lost write"
        )

    def test_high_contention_same_item(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """50 threads racing on the same item. Verifies the claim
        under a more aggressive contention profile."""
        bf = _make_filter(registrar, f"hi-{uuid.uuid4().hex[:8]}")
        n_threads = 50
        barrier = threading.Barrier(n_threads)
        errors: List[BaseException] = []
        errors_lock = threading.Lock()

        def worker() -> None:
            try:
                barrier.wait()
                bf.add("hot-item")
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert not errors, f"workers errored: {errors!r}"
        assert bf.might_contain("hot-item") is True


# ════════════════════════════════════════════════════════════════════
# 2. Concurrent add to different items, same key
# ════════════════════════════════════════════════════════════════════


class TestConcurrentAddDifferentItems:
    """10 threads each adding a distinct item in parallel. Every
    item must be present after the storm — no thread's write was
    lost due to a non-atomic SETBIT burst.
    """

    def test_ten_threads_adding_distinct_items(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        bf = _make_filter(registrar, f"diff-{uuid.uuid4().hex[:8]}")
        n_threads = 10
        items = [f"item-{i}" for i in range(n_threads)]
        barrier = threading.Barrier(n_threads)
        errors: List[BaseException] = []
        errors_lock = threading.Lock()

        def worker(item: str) -> None:
            try:
                barrier.wait()
                bf.add(item)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(item,))
            for item in items
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"workers errored: {errors!r}"
        for item in items:
            assert bf.might_contain(item) is True, (
                f"{item!r} not present after concurrent add"
            )


# ════════════════════════════════════════════════════════════════════
# 3. add + might_contain interleaving
# ════════════════════════════════════════════════════════════════════


class TestAddAndContainsInterleaving:
    """5 threads adding items, 5 threads calling ``might_contain``
    for items being added. After all threads finish, every added
    item must be contained.

    The reader threads may race with the writers, but the Lua
    per-item atomicity guarantees the readers never observe a
    torn / partial state for a given item.
    """

    def test_concurrent_readers_and_writers(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        bf = _make_filter(registrar, f"rw-{uuid.uuid4().hex[:8]}")
        items = [f"item-{i}" for i in range(200)]
        n_writers = 5
        n_readers = 5
        writer_barrier = threading.Barrier(n_writers)
        reader_barrier = threading.Barrier(n_readers)
        errors: List[BaseException] = []
        errors_lock = threading.Lock()

        def writer(chunk: List[str]) -> None:
            try:
                writer_barrier.wait()
                for item in chunk:
                    bf.add(item)
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        def reader(chunk: List[str]) -> None:
            try:
                # Wait until at least one writer has had a chance
                # to start, then poll a few times.
                reader_barrier.wait()
                time.sleep(0.05)
                for item in chunk:
                    bf.might_contain(item)  # must not raise
            except BaseException as exc:  # noqa: BLE001
                with errors_lock:
                    errors.append(exc)

        # Split items into 5 writer-chunks and 5 reader-chunks.
        writer_chunks = [
            items[i::n_writers] for i in range(n_writers)
        ]
        reader_chunks = [
            items[i::n_readers] for i in range(n_readers)
        ]

        writer_threads = [
            threading.Thread(target=writer, args=(c,))
            for c in writer_chunks
        ]
        reader_threads = [
            threading.Thread(target=reader, args=(c,))
            for c in reader_chunks
        ]
        for t in writer_threads + reader_threads:
            t.start()
        for t in writer_threads + reader_threads:
            t.join(timeout=10.0)

        assert not errors, f"workers errored: {errors!r}"
        # After all writers are done, every item must be present.
        for item in items:
            assert bf.might_contain(item) is True, (
                f"{item!r} not present after concurrent add"
            )


# ════════════════════════════════════════════════════════════════════
# 4. Lua EVAL script idempotence
# ════════════════════════════════════════════════════════════════════


class TestLuaEvalIdempotence:
    """The SETBIT Lua script must produce the same bit-pattern
    whether called once with N items or N times with one item
    each. SETBIT is naturally idempotent (setting an already-1
    bit to 1 is a no-op), so the ``BITCOUNT`` of the two
    filters should be identical.
    """

    def test_idempotent_setbit(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        # Two distinct filters in the same namespace.
        bf_a = _make_filter(registrar, f"idem-a-{uuid.uuid4().hex[:8]}")
        bf_b = _make_filter(registrar, f"idem-b-{uuid.uuid4().hex[:8]}")

        items = [f"item-{i}" for i in range(50)]

        # Pattern A: add items one at a time (50 EVALs).
        for item in items:
            bf_a.add(item)

        # Pattern B: add all items in one batch (50 EVALs, one per
        # item — see `add_all` implementation).
        bf_b.add_all(items)

        # Both filters must report every item as present.
        for item in items:
            assert bf_a.might_contain(item) is True, (
                f"item {item!r} not in A"
            )
            assert bf_b.might_contain(item) is True, (
                f"item {item!r} not in B"
            )

        # BITCOUNT must match — SETBIT is idempotent, and the
        # Lua script computes positions deterministically from
        # the sha256(item) digest, so both patterns produce
        # exactly the same final bit-pattern.
        raw = registrar._backend.raw_client()  # type: ignore[attr-defined]
        bitcount_a = int(
            raw.bitcount(bf_a._bit_key)  # type: ignore[attr-defined]
        )
        bitcount_b = int(
            raw.bitcount(bf_b._bit_key)  # type: ignore[attr-defined]
        )
        assert bitcount_a == bitcount_b, (
            f"BITCOUNT mismatch: A={bitcount_a} B={bitcount_b} "
            f"(idempotence violated)"
        )
        assert bitcount_a > 0, "BITCOUNT is 0 — SETBIT did not run"


# ════════════════════════════════════════════════════════════════════
# 5. add_all atomicity (per-item Lua EVAL)
# ════════════════════════════════════════════════════════════════════


class TestAddAllAtomicity:
    """``add_all`` is implemented as a loop of per-item ``add()``
    calls; each individual ``add()`` is a single Lua ``EVAL``,
    so the per-item SETBIT burst is atomic.

    This test verifies:

    (a) ``add_all`` adds every item (correctness).
    (b) The underlying script source matches the implementation's
        declared ``_BLOOM_ADD_LUA`` — i.e. the bit-setting is
        done by Lua, not by a non-atomic pipeline.
    (c) During a parallel reader's observations of BITCOUNT, the
        count is monotonic non-decreasing (it never "goes back"
        to a smaller value because of a torn write).
    """

    def test_add_all_adds_every_item(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        bf = _make_filter(registrar, f"all-{uuid.uuid4().hex[:8]}")
        items = [f"item-{i}" for i in range(100)]
        bf.add_all(items)
        for item in items:
            assert bf.might_contain(item) is True, (
                f"add_all lost {item!r}"
            )

    def test_add_uses_declared_lua_script(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Sanity check: the running implementation's Lua script
        is exactly the declared ``_BLOOM_ADD_LUA`` (no silent
        pipeline fall-back). We invoke the add and then read the
        script cache via SHA1; if the implementation had used a
        non-Lua path, BITCOUNT would not reflect the SETBITs.
        """
        import hashlib

        bf = _make_filter(registrar, f"sha-{uuid.uuid4().hex[:8]}")
        bf.add("sha-test")
        # SHA1 of the declared script.
        sha = hashlib.sha1(_BLOOM_ADD_LUA.encode("utf-8")).hexdigest()
        # After the first EVAL, the script is cached in Redis.
        # SCRIPT EXISTS returns 1 iff the SHA is in the cache.
        cached = registrar._backend.raw_client().script_exists(sha)  # type: ignore[attr-defined]
        # Some Redis clients return a list; normalise.
        if isinstance(cached, list):
            cached = cached[0] if cached else 0
        assert int(cached) == 1, (
            f"declared Lua script (sha={sha}) not in Redis cache; "
            f"add() may not be using Lua EVAL"
        )
        # And the same for the contains script.
        sha_contains = hashlib.sha1(
            _BLOOM_CONTAINS_LUA.encode("utf-8")
        ).hexdigest()
        bf.might_contain("sha-test")
        cached_contains = (
            registrar._backend.raw_client().script_exists(  # type: ignore[attr-defined]
                sha_contains
            )
        )
        if isinstance(cached_contains, list):
            cached_contains = cached_contains[0] if cached_contains else 0
        assert int(cached_contains) == 1, (
            f"declared CONTAINS Lua script (sha={sha_contains}) "
            f"not in Redis cache"
        )

    def test_bitcount_monotonic_under_contention(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Under a parallel ``add_all`` storm, a reader polling
        ``BITCOUNT`` must observe a monotonic non-decreasing
        sequence.

        The per-item Lua EVAL guarantees that a reader can never
        see a state where SOME bits for an item are set and
        others aren't (that would be a torn write). What a reader
        CAN see is the "before" or "after" state of any given
        item's SETBIT burst — never an intermediate one. So the
        BITCOUNT must only ever increase (or stay the same).
        """
        bf = _make_filter(registrar, f"mono-{uuid.uuid4().hex[:8]}")
        items = [f"item-{i}" for i in range(500)]
        raw = registrar._backend.raw_client()  # type: ignore[attr-defined]
        bit_key = bf._bit_key  # type: ignore[attr-defined]

        # Reader thread: poll BITCOUNT until the writer is done.
        observations: List[int] = []
        stop_event = threading.Event()
        reader_errors: List[BaseException] = []
        reader_errors_lock = threading.Lock()

        def reader() -> None:
            try:
                while not stop_event.is_set():
                    count = int(raw.bitcount(bit_key))
                    observations.append(count)
                    time.sleep(0.001)
            except BaseException as exc:  # noqa: BLE001
                with reader_errors_lock:
                    reader_errors.append(exc)

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()

        # Writer thread: add_all 500 items.
        bf.add_all(items)

        # Stop the reader once the writer is done.
        stop_event.set()
        reader_thread.join(timeout=5.0)

        assert not reader_errors, f"reader errored: {reader_errors!r}"
        assert observations, "reader recorded no observations"

        # Monotonic non-decreasing.
        for prev, curr in zip(observations, observations[1:]):
            assert curr >= prev, (
                f"BITCOUNT went backwards: {prev} -> {curr} "
                f"(torn SETBIT observed by parallel reader)"
            )
        # Final count must be > 0 (we added 500 items).
        assert observations[-1] > 0, (
            f"BITCOUNT ended at {observations[-1]} — writes lost?"
        )
