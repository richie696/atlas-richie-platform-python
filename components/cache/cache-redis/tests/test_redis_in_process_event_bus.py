"""Tests for the R-226 in-process event bus on `RedisEventManager`.

The M3.A `RedisEventManager` already supports Redis keyspace events
(`subscribe_key_event`). R-226 adds the in-process pub-sub:
  - `register_listener(event, callback)` / `on(event, callback)`
  - `unregister_listener(event, callback)` → bool
  - `fire(event, payload)` → listener count fired
  - `listener_count(event)` → int

Coverage:
  - basic register + fire round-trip
  - multiple listeners on the same event (fire in registration order)
  - unregister removes a listener
  - listener exception does not stop the bus; subsequent listeners fire
  - `on()` is an alias for `register_listener()`
  - firing an event with no listeners is a no-op (returns 0)
  - listener_count reflects the current state
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Iterator

import pytest
import redis as redis_lib

from atlas_richie.cache_redis import (
    RedisEventManager,
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
    namespace = f"R-226-E2E:{uuid.uuid4().hex[:8]}"
    reg = RedisProviderRegistrar(
        client, namespace=namespace, connection_string=REDIS_URL
    )
    try:
        yield reg
    finally:
        reg.close()


class TestInProcessEventBus:
    def test_basic_fire_delivers_payload(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr: RedisEventManager = registrar.event_ops()
        received: list[Any] = []
        mgr.register_listener("user.login", lambda p: received.append(p))
        n = mgr.fire("user.login", {"user": 42})
        assert n == 1
        assert received == [{"user": 42}]
        print("  ✅ basic fire delivers payload")

    def test_on_is_alias_for_register_listener(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        received: list[Any] = []
        mgr.on("alias.test", lambda p: received.append(p))
        mgr.fire("alias.test", "hi")
        assert received == ["hi"]
        print("  ✅ on() alias for register_listener()")

    def test_multiple_listeners_in_registration_order(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        order: list[str] = []
        mgr.register_listener("multi", lambda _: order.append("a"))
        mgr.register_listener("multi", lambda _: order.append("b"))
        mgr.register_listener("multi", lambda _: order.append("c"))
        n = mgr.fire("multi")
        assert n == 3
        assert order == ["a", "b", "c"]
        print("  ✅ multiple listeners fire in registration order")

    def test_unregister_removes_listener(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        received: list[Any] = []
        cb = lambda p: received.append(p)  # noqa: E731
        mgr.register_listener("ev", cb)
        assert mgr.unregister_listener("ev", cb) is True
        mgr.fire("ev", "v")
        assert received == []
        # Unregistering again returns False.
        assert mgr.unregister_listener("ev", cb) is False
        print("  ✅ unregister removes listener")

    def test_fire_with_no_listeners_is_noop(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        n = mgr.fire("nothing-listening", "payload")
        assert n == 0
        print("  ✅ fire with no listeners returns 0")

    def test_listener_exception_does_not_stop_bus(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        order: list[str] = []
        mgr.register_listener(
            "exc", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        mgr.register_listener("exc", lambda _: order.append("after"))
        n = mgr.fire("exc")
        # Both listeners are invoked (the second despite the first
        # raising).
        assert n == 2
        assert order == ["after"]
        print("  ✅ listener exception does not stop bus")

    def test_listener_count_tracks_state(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        assert mgr.listener_count("empty") == 0
        cb1 = lambda p: None  # noqa: E731
        cb2 = lambda p: None  # noqa: E731
        mgr.register_listener("ev", cb1)
        mgr.register_listener("ev", cb2)
        assert mgr.listener_count("ev") == 2
        mgr.unregister_listener("ev", cb1)
        assert mgr.listener_count("ev") == 1
        print("  ✅ listener_count tracks state")

    def test_payload_can_be_any_type(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        received: list[Any] = []
        mgr.register_listener("typed", lambda p: received.append(p))
        mgr.fire("typed", "str")
        mgr.fire("typed", 42)
        mgr.fire("typed", {"a": 1})
        mgr.fire("typed", [1, 2, 3])
        mgr.fire("typed", None)
        assert received == ["str", 42, {"a": 1}, [1, 2, 3], None]
        print("  ✅ payload can be any type")

    def test_different_events_isolated(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        a: list[Any] = []
        b: list[Any] = []
        mgr.register_listener("a", lambda p: a.append(p))
        mgr.register_listener("b", lambda p: b.append(p))
        mgr.fire("a", 1)
        mgr.fire("b", 2)
        assert a == [1]
        assert b == [2]
        print("  ✅ different events are isolated")

    def test_unregister_unknown_event_returns_false(
        self, registrar: RedisProviderRegistrar
    ) -> None:
        mgr = registrar.event_ops()
        assert mgr.unregister_listener("never-registered", lambda p: None) is False
        print("  ✅ unregister on unknown event returns False")
