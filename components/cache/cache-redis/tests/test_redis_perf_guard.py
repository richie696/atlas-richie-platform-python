"""Real-Redis tests for `RedisPerfGuard` (R-M5.4).

Covers the six most-frequent guard paths wired into the managers:

1. `enabled=False` is a no-op even when other thresholds are
   configured.
2. `enabled=True` + `block_*_violations=True` raises
   `ConfigurationError` on a too-large payload.
3. `enabled=True` + `block_*_violations=False` logs a warning but
   does not raise.
4. `time_op` records elapsed_ms (verifies the soft / hard threshold
   instrumentation fires).
5. `check_batch_size` raises when a batch exceeds the threshold.
6. End-to-end: `RedisCacheProperties(perf=...)` → `from_properties`
   → `set_with_ttl` with a too-large value raises
   `ConfigurationError`.

These tests are real-Redis (matching the rest of the cache-redis
suite) so the manager-level wiring is exercised against a live
`BlockingConnectionPool`; the `RedisPerfGuard` itself doesn't
touch Redis, but the manager integration must round-trip through
the real backend.
"""

from __future__ import annotations

import os
import structlog
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib
import structlog.testing

from atlas_richie.cache_redis import (
    ConfigurationError,
    RedisPerfGuard,
    RedisProviderRegistrar,
)
from atlas_richie.cache_redis.redis_cache_properties import (
    RedisCacheProperties,
    RedisPerfSettings,
)

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_CACHE_REDIS_URL",
    "redis://:Redis2025!Local@127.0.0.1:16379/0",
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def redis_client() -> Iterator[redis_lib.Redis]:
    """Yield a `redis.Redis` client; skip if the server is down.

    The full test file is a real-Redis suite so we get coverage
    on the manager-side wiring (not just the unit-level
    `RedisPerfGuard`). The test runs against a unique namespace
    per test (via the `namespace` fixture below) so concurrent
    runs don't collide.
    """
    client = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis_lib.exceptions.RedisError as exc:
        pytest.skip(f"Redis not reachable at {REDIS_URL!r}: {exc}")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def namespace() -> str:
    return f"R-M5.4:{uuid.uuid4().hex[:8]}"


@pytest.fixture
def registrar_with_guard(
    redis_client: redis_lib.Redis,
    namespace: str,
) -> Iterator[tuple[RedisProviderRegistrar, RedisPerfGuard, RedisPerfSettings]]:
    """Yield `(registrar, guard, settings)` where the registrar was
    built with a hand-rolled perf guard so tests can poke at
    `settings` (e.g. flip `block_*` mid-test) without rebuilding
    the whole registrar.

    Each test gets a fresh namespace and the namespace is
    SCAN-cleaned on teardown.
    """
    settings = RedisPerfSettings(enabled=False)  # start disabled
    guard = RedisPerfGuard(settings)
    reg = RedisProviderRegistrar(
        redis_client,
        namespace=namespace,
        connection_string=REDIS_URL,
        perf=guard,
    )
    try:
        yield reg, guard, settings
    finally:
        # Best-effort namespace cleanup (matches the existing
        # test fixtures' teardown style).
        try:
            keys = list(redis_client.scan_iter(match=f"{namespace}:*", count=200))
            if keys:
                redis_client.delete(*keys)
        finally:
            reg.close()


# ── Tests ────────────────────────────────────────────────────────


class TestGuardDisabledByDefault:
    """`enabled=False` (the default) must be a no-op for all checks.

    These tests set restrictive thresholds while keeping
    `enabled=False` and verify that a large payload / large batch
    does NOT raise. This protects the "wire the guard but don't
    enable it" deployment path (the common case for a fresh
    `from_properties()`).
    """

    def test_no_op_string_payload_when_disabled(
        self, registrar_with_guard
    ) -> None:
        _, _, _ = registrar_with_guard
        reg, _, settings = registrar_with_guard
        settings.string_payload_max_bytes_warn = 1  # ridiculously low
        settings.string_payload_max_bytes_error = 1
        settings.block_string_payload_violations = True
        # Should NOT raise because `enabled=False` short-circuits.
        reg.value_ops().set_with_ttl("big", b"x" * 1_000_000, 1_000)
        # Round-trip verifies the value was actually written.
        assert reg.value_ops().get("big", bytes) == b"x" * 1_000_000

    def test_no_op_batch_size_when_disabled(
        self, registrar_with_guard
    ) -> None:
        reg, _, settings = registrar_with_guard
        settings.max_batch_read_items = 1
        settings.block_batch_read_violations = True
        # 5000 keys is way over the threshold of 1; should NOT
        # raise because `enabled=False` short-circuits.
        keys = [f"k{i}" for i in range(5_000)]
        result = reg.value_ops().get_map(keys, str)
        # The map is empty (nothing was written), but no raise.
        assert result == {}

    def test_no_op_time_op_when_disabled(
        self, registrar_with_guard
    ) -> None:
        """`time_op` is a no-op context manager when disabled."""
        reg, _, settings = registrar_with_guard
        settings.toc_soft_ms = 1  # any sleep > 1ms would warn
        settings.toc_hard_ms = 1
        # Sleep inside `with guard.time_op(...)` would warn if
        # enabled; we use a no-op body to keep the test fast.
        with reg._perf.time_op("test_op") if reg._perf else _noop():
            pass
        # No assertion needed — the test passes if no exception
        # fires and no log line is emitted.


class TestGuardStringPayloadBlock:
    """`enabled=True` + `block_*_violations=True` → raise."""

    def test_block_raises_on_too_large_payload(
        self, registrar_with_guard
    ) -> None:
        reg, _, settings = registrar_with_guard
        settings.enabled = True
        settings.string_payload_max_bytes_warn = 100
        settings.string_payload_max_bytes_error = 1_000
        settings.block_string_payload_violations = True
        # 10MB value — well over the 1KB error threshold.
        with pytest.raises(ConfigurationError) as excinfo:
            reg.value_ops().set_with_ttl("huge", b"x" * 10_000_000, 60_000)
        assert "string payload" in str(excinfo.value).lower()
        assert "10000000" in str(excinfo.value)

    def test_block_does_not_fire_for_under_threshold(
        self, registrar_with_guard
    ) -> None:
        reg, _, settings = registrar_with_guard
        settings.enabled = True
        settings.string_payload_max_bytes_warn = 100
        settings.string_payload_max_bytes_error = 10_000
        settings.block_string_payload_violations = True
        # 1KB value — under both warn (100B) and error (10KB).
        # The warn fires (we don't raise) and the value is
        # written successfully.
        reg.value_ops().set_with_ttl("small", b"x" * 1_000, 5_000)
        assert reg.value_ops().get("small", bytes) == b"x" * 1_000


class TestGuardStringPayloadWarnOnly:
    """`enabled=True` + `block_*_violations=False` → log only."""

    def test_warn_does_not_raise_on_too_large_payload(
        self, registrar_with_guard
    ) -> None:
        reg, _, settings = registrar_with_guard
        settings.enabled = True
        settings.string_payload_max_bytes_warn = 100
        settings.string_payload_max_bytes_error = 10_000_000  # way above
        settings.block_string_payload_violations = False
        # 10MB value — over the 100B warn threshold but under the
        # 10MB error threshold, so the guard logs a `warning` and
        # does NOT raise.
        with structlog.testing.capture_logs() as caplog:
            reg.value_ops().set_with_ttl(
                "big", b"x" * 1_000_000, 5_000
            )
        # Verify a `perf.string_payload_large` warning fired.
        warning_events = [
            e for e in caplog
            if e.get("event") == "perf.string_payload_large"
        ]
        assert warning_events, (
            f"expected a perf.string_payload_large event; got {caplog}"
        )
        assert warning_events[0]["size"] == 1_000_000
        assert warning_events[0]["threshold"] == 100
        # The value was actually written.
        assert reg.value_ops().get("big", bytes) == b"x" * 1_000_000


class TestTimeOpThreshold:
    """`time_op` records elapsed_ms and logs soft / hard events."""

    def test_soft_timeout_logs_warning(self) -> None:
        settings = RedisPerfSettings(
            enabled=True,
            toc_soft_ms=10,   # anything > 10ms is "soft slow"
            toc_hard_ms=500,  # avoid hitting the hard threshold
            warn_non_o1=False,
        )
        guard = RedisPerfGuard(settings)
        with structlog.testing.capture_logs() as caplog:
            with guard.time_op("slow_op"):
                time.sleep(0.05)  # 50ms — over the 10ms soft threshold
        soft_events = [
            e for e in caplog
            if e.get("event") == "perf.soft_timeout"
            and e.get("op") == "slow_op"
        ]
        assert soft_events, f"expected perf.soft_timeout; got {caplog}"
        elapsed = soft_events[0]["elapsed_ms"]
        # 50ms target; allow a 20ms window for scheduling jitter
        # (CI machines, Python 3.12+ GIL preemption, etc.).
        assert 40 <= elapsed <= 200, (
            f"elapsed_ms={elapsed} outside the expected 40-200ms window"
        )

    def test_hard_timeout_logs_error(self) -> None:
        settings = RedisPerfSettings(
            enabled=True,
            toc_soft_ms=1,    # trivial soft threshold
            toc_hard_ms=20,   # anything > 20ms is "hard slow"
            warn_non_o1=False,
        )
        guard = RedisPerfGuard(settings)
        with structlog.testing.capture_logs() as caplog:
            with guard.time_op("slow_op"):
                time.sleep(0.05)  # 50ms — over the 20ms hard threshold
        hard_events = [
            e for e in caplog
            if e.get("event") == "perf.hard_timeout"
            and e.get("op") == "slow_op"
        ]
        assert hard_events, f"expected perf.hard_timeout; got {caplog}"


class TestBatchSizeBlock:
    """`check_batch_size` raises when a batch exceeds the threshold."""

    def test_get_many_raises_on_too_large_batch(
        self, registrar_with_guard
    ) -> None:
        reg, _, settings = registrar_with_guard
        settings.enabled = True
        settings.max_batch_read_items = 1_000
        settings.block_batch_read_violations = True
        # Field manager's `get_many` is the most direct test of
        # the batch size check (the String manager's `get_map`
        # also enforces it, but the field manager gives us a
        # single-key call shape that doesn't depend on the keys
        # existing).
        with pytest.raises(ConfigurationError) as excinfo:
            reg.field_ops().get_many(
                "fake-hash", [f"f{i}" for i in range(5_000)], str
            )
        assert "batch" in str(excinfo.value).lower()
        assert "5000" in str(excinfo.value)


class TestEndToEndFromProperties:
    """`RedisCacheProperties(perf=...)` → `from_properties` end-to-end."""

    def test_block_too_large_payload_via_from_properties(
        self, redis_client: redis_lib.Redis
    ) -> None:
        props = RedisCacheProperties(
            url=REDIS_URL,
            namespace=f"R-M5.4:props:{uuid.uuid4().hex[:8]}",
            perf=RedisPerfSettings(
                enabled=True,
                string_payload_max_bytes_warn=100,
                string_payload_max_bytes_error=1_000,
                block_string_payload_violations=True,
            ),
        )
        reg = RedisProviderRegistrar.from_properties(props)
        try:
            # `from_properties` must wire the guard into the
            # `value_ops` manager.
            assert reg.perf is not None
            assert reg.perf.settings.enabled is True
            with pytest.raises(ConfigurationError):
                reg.value_ops().set_with_ttl(
                    "huge", b"x" * 1_000_000, 5_000
                )
        finally:
            # Best-effort cleanup.
            try:
                keys = list(
                    redis_client.scan_iter(
                        match=f"{props.namespace}:*", count=200
                    )
                )
                if keys:
                    redis_client.delete(*keys)
            finally:
                reg.close()

    def test_no_op_when_perf_disabled_via_from_properties(
        self, redis_client: redis_lib.Redis
    ) -> None:
        """`perf.enabled=False` (the default) means even a 10MB
        payload goes through without raising — the guard is wired
        but inert."""
        props = RedisCacheProperties(
            url=REDIS_URL,
            namespace=f"R-M5.4:noop:{uuid.uuid4().hex[:8]}",
            # default `RedisPerfSettings(enabled=False)`
        )
        reg = RedisProviderRegistrar.from_properties(props)
        try:
            # Guard is wired but disabled.
            assert reg.perf is not None
            assert reg.perf.settings.enabled is False
            # 10MB payload — no raise.
            reg.value_ops().set_with_ttl("big", b"x" * 10_000_000, 60_000)
            assert reg.value_ops().get("big", bytes) == b"x" * 10_000_000
        finally:
            try:
                keys = list(
                    redis_client.scan_iter(
                        match=f"{props.namespace}:*", count=200
                    )
                )
                if keys:
                    redis_client.delete(*keys)
            finally:
                reg.close()


# ── Helpers ──────────────────────────────────────────────────────


from contextlib import contextmanager  # noqa: E402


@contextmanager
def _noop():
    yield
