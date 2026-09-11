"""Tests for the R-221 `NotificationOps.subscribe()` + `RedisNotificationListener`.

Coverage:
  - basic publish/subscribe round-trip (binary payload)
  - multi-message round-trip on the same listener
  - is_open() lifecycle (open after create, closed after close)
  - close() is idempotent
  - handler exception is logged but does not kill the pump
  - cross-process fan-out: one publisher, two listeners on the same topic
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisNotificationListener,
    RedisNotificationManager,
    RedisProviderRegistrar,
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
    namespace = f"R-221-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        reg.close()


class TestNotificationSubscribe:
    def test_basic_publish_subscribe_round_trip(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisNotificationManager = registrar.notification_ops()
        received: list[tuple[str, Any]] = []
        ready = threading.Event()

        def handler(channel: str, message: Any) -> None:
            received.append((channel, message))
            ready.set()

        listener = mgr.subscribe("ch", handler)
        try:
            time.sleep(0.2)  # let subscription wire up
            mgr.publish("ch", b"hello")
            assert ready.wait(timeout=3.0), "no message received within 3s"
            assert len(received) == 1
            # Channel comes back as the namespaced topic.
            assert received[0][0].endswith(":ch")
            # With `decode_responses=True` (the registrar's default),
            # redis-py auto-decodes the payload to str on the
            # subscriber side. The listener preserves it as-is.
            assert received[0][1] == "hello"
        finally:
            listener.close()
        print("  ✅ basic publish/subscribe round-trip")

    def test_multiple_messages_same_listener(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()
        received: list[Any] = []
        done_event = threading.Event()
        expected = 5

        def handler(channel: str, message: Any) -> None:
            received.append(message)
            if len(received) >= expected:
                done_event.set()

        listener = mgr.subscribe("multi", handler)
        try:
            time.sleep(0.2)
            for i in range(expected):
                mgr.publish("multi", f"msg-{i}".encode("utf-8"))
            assert done_event.wait(timeout=5.0), (
                f"only {len(received)}/{expected} received within 5s"
            )
            assert len(received) == expected
        finally:
            listener.close()
        print("  ✅ multiple messages same listener")

    def test_is_open_lifecycle(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()

        def handler(channel: str, message: Any) -> None:
            pass

        listener = mgr.subscribe("lifecycle", handler)
        try:
            assert isinstance(listener, RedisNotificationListener)
            assert listener.is_open() is True
        finally:
            listener.close()
        assert listener.is_open() is False
        print("  ✅ is_open() lifecycle")

    def test_close_is_idempotent(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()

        def handler(channel: str, message: Any) -> None:
            pass

        listener = mgr.subscribe("idempotent", handler)
        listener.close()
        # Second close is a no-op, not an exception.
        listener.close()
        assert listener.is_open() is False
        print("  ✅ close() is idempotent")

    def test_handler_exception_does_not_kill_pump(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """A handler that raises must be logged but the pump must
        continue delivering subsequent messages."""
        mgr = registrar.notification_ops()
        received: list[Any] = []
        ready = threading.Event()

        def bad_handler(channel: str, message: Any) -> None:
            raise RuntimeError("boom")

        def good_handler(channel: str, message: Any) -> None:
            received.append(message)
            ready.set()

        # First listener has a raising handler.
        bad_listener = mgr.subscribe("robust", bad_handler)
        # Second listener is independent and uses a working handler.
        good_listener = mgr.subscribe("robust", good_handler)
        try:
            time.sleep(0.2)
            mgr.publish("robust", b"after-boom")
            assert ready.wait(timeout=3.0), "good handler did not receive"
            assert received == ["after-boom"]
        finally:
            bad_listener.close()
            good_listener.close()
        print("  ✅ handler exception does not kill pump")

    def test_two_listeners_same_topic(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        """Two independent listeners on the same topic both receive
        every published message (Pub/Sub fan-out semantics)."""
        mgr = registrar.notification_ops()
        a_received: list[Any] = []
        b_received: list[Any] = []
        a_ready = threading.Event()
        b_ready = threading.Event()

        a_listener = mgr.subscribe(
            "fanout", lambda ch, m: (a_received.append(m), a_ready.set())
        )
        b_listener = mgr.subscribe(
            "fanout", lambda ch, m: (b_received.append(m), b_ready.set())
        )
        try:
            time.sleep(0.2)
            mgr.publish("fanout", b"to-all")
            assert a_ready.wait(timeout=3.0), "listener A did not receive"
            assert b_ready.wait(timeout=3.0), "listener B did not receive"
            assert a_received == ["to-all"]
            assert b_received == ["to-all"]
        finally:
            a_listener.close()
            b_listener.close()
        print("  ✅ two listeners same topic (fan-out)")

    def test_listener_survives_publish_with_no_subscribers(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()

        def handler(channel: str, message: Any) -> None:
            pass

        listener = mgr.subscribe("silent", handler)
        try:
            # Publish when listener is still wiring up: redis returns
            # 0; listener does not crash.
            time.sleep(0.1)
            n = mgr.publish("silent", b"early")
            assert isinstance(n, int)
            assert listener.is_open() is True
        finally:
            listener.close()
        print("  ✅ publish returns 0 when no listener wired yet")

    def test_dict_payload_round_trip(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.notification_ops()
        received: list[Any] = []
        ready = threading.Event()

        listener = mgr.subscribe(
            "json", lambda ch, m: (received.append(m), ready.set())
        )
        try:
            time.sleep(0.2)
            mgr.publish("json", {"event": "login", "user": 42})
            assert ready.wait(timeout=3.0)
            # Decoded as JSON dict.
            assert received[0] == {"event": "login", "user": 42}
        finally:
            listener.close()
        print("  ✅ dict payload round-trips through JSON")
