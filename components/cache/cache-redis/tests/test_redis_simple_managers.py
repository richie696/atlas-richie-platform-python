"""Real-Redis smoke tests for the four smaller M3.A managers:

- `RedisScriptManager` (ScriptOps): thin `EVAL` wrapper.
- `RedisLimiterManager` (LimiterOps): atomic INCR + EXPIRE via Lua.
- `RedisNotificationManager` (NotificationOps + NotificationFunction):
  Pub/Sub publish.
- `RedisEventManager` (EventOps + EventFunction): keyspace event
  subscription (verifies the subscription wiring; actual event
  delivery needs `notify-keyspace-events` enabled on the server,
  which our local Redis does not have).

Tests are kept focused on the core round-trip; the goal of M3.A is
to validate the manager pattern at the four smallest interfaces
before tackling the larger data-structure managers in M3.B.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_core.contracts.keyspace_listener import (
    KeyspaceEventListener,
)

from atlas_richie.cache_redis import (
    RedisEventManager,
    RedisLimiterManager,
    RedisNotificationManager,
    RedisProviderRegistrar,
    RedisScriptManager,
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
    namespace = f"R-220-M3A-Simple:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        try:
            keys = list(client.scan_iter(match=f"{namespace}:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            reg.close()


# ── ScriptOps ────────────────────────────────────────────────────────


class TestScriptOps:
    def test_eval_returns_int(self, registrar: RedisProviderRegistrar) -> None:
        mgr = registrar.script_ops()
        result = mgr.eval("return 42", [], [], int)
        assert result == 42

    def test_eval_returns_string(self, registrar: RedisProviderRegistrar) -> None:
        mgr = registrar.script_ops()
        result = mgr.eval("return 'hello'", [], [], str)
        assert result == "hello"

    def test_eval_passes_namespaced_key(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.script_ops()
        # `KEYS[1]` should be the namespaced key.
        result = mgr.eval("return KEYS[1]", ["mykey"], [], str)
        # The namespaced key has the registrar's namespace prefix.
        ns_prefix = f"{registrar.value_ops()._backend.namespace}:"
        assert result.startswith(ns_prefix)
        assert result.endswith(":mykey")

    def test_eval_passes_args(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.script_ops()
        result = mgr.eval("return ARGV[1] + ARGV[2]", [], ["3", "4"], int)
        assert result == 7

    def test_eval_single_key(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.script_ops()
        result = mgr.eval_single_key(
            "return 1 + 1", "ignored_key", [], int
        )
        assert result == 2

    def test_real_atomic_increment(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.script_ops()
        # A typical use: increment and return new value.
        result = mgr.eval(
            "return redis.call('INCR', KEYS[1])", ["counter"], [], int
        )
        assert result == 1
        result = mgr.eval(
            "return redis.call('INCR', KEYS[1])", ["counter"], [], int
        )
        assert result == 2


# ── LimiterOps ───────────────────────────────────────────────────────


class TestLimiterOps:
    def test_first_request_within_window(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.limiter_ops()
        assert mgr.try_acquire("rate:user:1", max_count=3, window_seconds=10) is True

    def test_second_request_within_window(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.limiter_ops()
        assert mgr.try_acquire("rate:user:2", max_count=3, window_seconds=10) is True
        assert mgr.try_acquire("rate:user:2", max_count=3, window_seconds=10) is True
        assert mgr.try_acquire("rate:user:2", max_count=3, window_seconds=10) is True
        # 4th request exceeds the limit.
        assert mgr.try_acquire("rate:user:2", max_count=3, window_seconds=10) is False

    def test_expiry_set_on_first_request(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.limiter_ops()
        mgr.try_acquire("rate:user:3", max_count=100, window_seconds=5)
        # The key was created with EXPIRE on the first request.
        ttl = registrar.key_ops().get_expire("rate:user:3")
        # `get_expire` returns -1 (no TTL) if the script logic was
        # wrong; otherwise TTL is close to 5000 ms.
        assert ttl > 0, f"expected TTL > 0, got {ttl}"
        assert ttl <= 5_000

    def test_independent_counters(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.limiter_ops()
        # Max out user A.
        for _ in range(3):
            mgr.try_acquire("rate:user:A", max_count=3, window_seconds=10)
        assert mgr.try_acquire("rate:user:A", max_count=3, window_seconds=10) is False
        # User B is unaffected.
        assert mgr.try_acquire("rate:user:B", max_count=3, window_seconds=10) is True


# ── NotificationOps + NotificationFunction ──────────────────────────


class TestNotificationOps:
    def test_publish_no_subscribers(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()
        # 0 subscribers when no one is listening.
        assert mgr.publish("topic:no:listeners", "hello") == 0

    def test_publish_with_local_subscriber(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()
        raw_client = registrar.value_ops()._backend.raw_client()
        pubsub = raw_client.pubsub()
        try:
            pubsub.subscribe(registrar.value_ops()._k("topic:pub"))
            # Give the subscribe time to land.
            time.sleep(0.1)
            n = mgr.publish("topic:pub", {"k": "v"})
            assert n >= 1, f"expected ≥ 1 subscriber, got {n}"
        finally:
            pubsub.close()

    def test_publish_notify_alias(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_function()
        raw_client = registrar.value_ops()._backend.raw_client()
        pubsub = raw_client.pubsub()
        try:
            pubsub.subscribe(registrar.value_ops()._k("topic:alias"))
            time.sleep(0.1)
            n = mgr.publish_notify("topic:alias", "payload")
            assert n >= 1
        finally:
            pubsub.close()

    def test_publish_serialises_complex(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Non-bytes values get JSON-encoded (per Java's
        `JsonUtils.serialize`)."""
        mgr = registrar.notification_ops()
        # Just verify it doesn't crash.
        n = mgr.publish("topic:complex", {"nested": {"a": 1, "b": [1, 2]}})
        assert n >= 0  # 0 if no subscribers, ≥ 1 otherwise.


# ── EventOps + EventFunction ────────────────────────────────────────


class _Recorder(KeyspaceEventListener):
    def __init__(self) -> None:
        self.events: list = []
        self._lock = threading.Lock()

    def on_message(self, pattern, channel, data) -> None:
        with self._lock:
            self.events.append((pattern, channel, data))


class TestEventOps:
    def test_subscribe_does_not_crash(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisEventManager = registrar.event_ops()
        listener = _Recorder()
        try:
            # `subscribe_key_event` returns None; the actual pump
            # thread runs in the background. We just verify wiring.
            mgr.subscribe_key_event("__keyevent@0__:expired", listener)
        finally:
            mgr.close()

    def test_event_function_returns_same_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisEventManager

        assert isinstance(registrar.event_function(), RedisEventManager)
        assert registrar.event_function() is registrar.event_ops()

    def test_close_stops_pump_threads(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisEventManager = registrar.event_ops()
        listener = _Recorder()
        mgr.subscribe_key_event("__keyevent@0__:expired", listener)
        mgr.close()
        # After close, no pump threads should remain. We can't
        # easily verify this from Python; we just check the
        # subscription dict is empty.
        assert mgr._subscriptions == {}


class TestProviderRegistrarWiring:
    def test_script_ops_is_script_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisScriptManager

        assert isinstance(registrar.script_ops(), RedisScriptManager)

    def test_limiter_ops_is_limiter_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisLimiterManager

        assert isinstance(registrar.limiter_ops(), RedisLimiterManager)

    def test_notification_ops_is_notification_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisNotificationManager

        assert isinstance(registrar.notification_ops(), RedisNotificationManager)

    def test_event_ops_is_event_manager(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        from atlas_richie.cache_redis import RedisEventManager

        assert isinstance(registrar.event_ops(), RedisEventManager)
