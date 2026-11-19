"""L1 store-by-value contract tests.

`store_by_value` decides whether the cache keeps a defensive copy of the
value or shares the caller's object.

The Python default is **True** (defensive copy on every read and write) —
unlike Java, whose `CacheDefinition.storeByValue` defaults to false. The
default is a deliberate deviation: the Python local cache has always copied
on every read and write, so flipping it would silently drop that
protection. The reference mode stays available as an explicit opt-out.
"""

from __future__ import annotations

import pytest

from atlas_richie.cache_core.local import (
    CacheDefinition,
    LocalCacheManager,
    LocalCacheProperties,
)

pytestmark = pytest.mark.unit

REGION = "store-by-value-region"


def _manager(
    *,
    store_by_value: bool = True,
    write_through: bool = False,
    read_through: bool = False,
) -> LocalCacheManager:
    definition = CacheDefinition(
        store_by_value=store_by_value,
        write_through=write_through,
        read_through=read_through,
    )
    return LocalCacheManager(
        properties=LocalCacheProperties(cache_definitions={REGION: definition})
    )


class TestStoreByValueDefault:
    def test_default_is_true(self) -> None:
        assert CacheDefinition().store_by_value is True

    def test_caller_mutation_does_not_reach_the_store(self) -> None:
        manager = _manager()
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)

        payload["items"].append(2)

        assert manager.get(REGION, "k") == {"items": [1]}

    def test_caller_mutation_does_not_reach_a_stored_object(self) -> None:
        manager = _manager()
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)
        fetched = manager.get(REGION, "k")

        fetched["items"].append(2)

        assert manager.get(REGION, "k") == {"items": [1]}

    def test_put_and_get_return_distinct_objects(self) -> None:
        manager = _manager()
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)
        fetched = manager.get(REGION, "k")
        assert fetched is not payload


class TestStoreByReference:
    def test_stored_object_is_shared_when_disabled(self) -> None:
        manager = _manager(store_by_value=False)
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)

        fetched = manager.get(REGION, "k")

        assert fetched is payload

    def test_caller_mutation_is_visible_when_disabled(self) -> None:
        manager = _manager(store_by_value=False)
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)

        payload["items"].append(2)

        assert manager.get(REGION, "k") == {"items": [1, 2]}


class TestStoreByValueWithStrategies:
    def test_write_through_receives_the_caller_object_when_disabled(self) -> None:
        manager = _manager(store_by_value=False, write_through=True)
        received: list[object] = []

        class _Writer:
            def write(self, key: str, value: object) -> None:
                received.append(value)

            def delete(self, key: str) -> None:
                return None

        manager.register_writer(REGION, _Writer())
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)

        assert received[0] is payload

    def test_write_through_receives_the_caller_object(self) -> None:
        """JSR-107 parity: the writer gets the value that was put.

        The cache keeps its own defensive copy, but the writer is handed
        the object the caller passed in — that is what the JCache
        reference implementation does, and the write is synchronous, so
        the caller cannot mutate the value before it is written back.
        """
        manager = _manager(store_by_value=True, write_through=True)
        received: list[object] = []

        class _Writer:
            def write(self, key: str, value: object) -> None:
                received.append(value)

            def delete(self, key: str) -> None:
                return None

        manager.register_writer(REGION, _Writer())
        payload = {"items": [1]}
        manager.put(REGION, "k", payload)

        assert received[0] is payload
        assert manager.get(REGION, "k") is not payload

    def test_read_through_value_is_stored_by_value(self) -> None:
        manager = _manager(store_by_value=True, read_through=True)
        source = {"k": {"items": [1]}}
        manager.register_loader(REGION, lambda key: source[key])

        fetched = manager.get(REGION, "k")
        fetched["items"].append(2)

        assert manager.get(REGION, "k") == {"items": [1]}
