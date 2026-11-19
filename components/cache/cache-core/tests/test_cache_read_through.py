"""L1 read-through contract tests.

A read-through region asks a registered loader for the value on a miss and
caches the result. Mirrors JSR-107 read-through semantics:

- the loader is invoked only on a miss;
- concurrent misses for the same key collapse into a single source load;
- `get_all` batch-loads the missing keys;
- a loader that returns `None` caches nothing.
"""

from __future__ import annotations

import threading
import time
from typing import Collection, Mapping

import pytest

from atlas_richie.cache_core.local import (
    CacheDefinition,
    LocalCacheManager,
    LocalCacheProperties,
)
from atlas_richie.cache_core.local.manage import (
    CallableCacheLoader,
    as_cache_loader,
)

pytestmark = pytest.mark.unit

REGION = "read-through-region"


class _RecordingLoader:
    """Loader that records every call and serves a fixed mapping."""

    def __init__(self, values: Mapping[str, object] | None = None) -> None:
        self.values = dict(values or {})
        self.calls: list[str] = []
        self.batch_calls: list[list[str]] = []

    def load(self, key: str) -> object | None:
        self.calls.append(key)
        return self.values.get(key)

    def load_all(self, keys: Collection[str]) -> Mapping[str, object]:
        self.batch_calls.append(list(keys))
        return {k: self.values[k] for k in keys if k in self.values}


def _manager(*, read_through: bool = True) -> LocalCacheManager:
    definition = CacheDefinition(read_through=read_through, statistics_enabled=True)
    return LocalCacheManager(
        properties=LocalCacheProperties(cache_definitions={REGION: definition})
    )


class TestReadThroughBasics:
    def test_miss_loads_from_the_source(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)

        assert manager.get(REGION, "k") == "v"
        assert loader.calls == ["k"]

    def test_loaded_value_is_cached(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)

        assert manager.get(REGION, "k") == "v"
        assert manager.get(REGION, "k") == "v"

        assert loader.calls == ["k"], "the second read is a hit, not a load"

    def test_hit_does_not_call_the_loader(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "cached")

        assert manager.get(REGION, "k") == "cached"
        assert loader.calls == []

    def test_loader_returning_none_caches_nothing(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({})
        manager.register_loader(REGION, loader)

        assert manager.get(REGION, "k") is None
        assert manager.contains_key(REGION, "k") is False
        assert loader.calls == ["k"]

    def test_disabled_region_never_calls_the_loader(self) -> None:
        manager = _manager(read_through=False)
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)

        assert manager.get(REGION, "k") is None
        assert loader.calls == []

    def test_region_without_a_loader_returns_none(self) -> None:
        manager = _manager()
        assert manager.get(REGION, "k") is None


class TestReadThroughRegistration:
    def test_loader_registered_after_bucket_creation_takes_effect(self) -> None:
        manager = _manager()
        manager.get(REGION, "k")          # creates the bucket first
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)

        assert manager.get(REGION, "k") == "v"
        assert loader.calls == ["k"]

    def test_plain_callable_is_accepted(self) -> None:
        manager = _manager()
        manager.register_loader(REGION, lambda key: f"value-{key}")
        assert manager.get(REGION, "k") == "value-k"

    def test_loader_object_is_accepted(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)
        assert manager.get(REGION, "k") == "v"

    def test_invalid_loader_is_rejected(self) -> None:
        manager = _manager()
        with pytest.raises(TypeError):
            manager.register_loader(REGION, 42)

    def test_as_cache_loader_wraps_a_callable(self) -> None:
        loader = as_cache_loader(lambda key: "v")
        assert isinstance(loader, CallableCacheLoader)
        assert loader.load("k") == "v"
        assert loader.load_all(["k"]) == {"k": "v"}

    def test_as_cache_loader_keeps_a_loader_object(self) -> None:
        loader = _RecordingLoader({"k": "v"})
        assert as_cache_loader(loader) is loader


class TestReadThroughBatch:
    def test_get_all_batch_loads_missing_keys(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"a": 1, "b": 2})
        manager.register_loader(REGION, loader)
        manager.put(REGION, "a", "cached")

        result = manager.get_all(REGION, ["a", "b", "c"])

        assert result["a"] == "cached"
        assert result["b"] == 2
        assert "c" not in result
        assert loader.batch_calls == [["b", "c"]]

    def test_batch_loaded_values_are_cached(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"b": 2})
        manager.register_loader(REGION, loader)

        manager.get_all(REGION, ["b"])
        assert manager.get(REGION, "b") == 2
        assert loader.calls == [], "the value is cached, no per-key load needed"


class TestReadThroughConcurrency:
    def test_concurrent_misses_collapse_into_one_load(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({"k": "v"})
        manager.register_loader(REGION, loader)

        barrier = threading.Barrier(8)
        results: list[object] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait()
            value = manager.get(REGION, "k")
            with lock:
                results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert results == ["v"] * 8
        assert loader.calls == ["k"], "one source load for eight concurrent misses"

    def test_distinct_keys_load_in_parallel(self) -> None:
        manager = _manager()
        loader = _RecordingLoader({f"k{i}": i for i in range(4)})
        manager.register_loader(REGION, loader)

        values = [manager.get(REGION, f"k{i}") for i in range(4)]
        assert values == [0, 1, 2, 3]
        assert sorted(loader.calls) == ["k0", "k1", "k2", "k3"]


class TestReadThroughFailure:
    def test_loader_exception_propagates(self) -> None:
        manager = _manager()

        def boom(key: str) -> object:
            raise RuntimeError("source down")

        manager.register_loader(REGION, boom)
        with pytest.raises(RuntimeError, match="source down"):
            manager.get(REGION, "k")

    def test_failed_load_leaves_the_entry_absent(self) -> None:
        manager = _manager()

        def boom(key: str) -> object:
            raise RuntimeError("source down")

        manager.register_loader(REGION, boom)
        with pytest.raises(RuntimeError):
            manager.get(REGION, "k")
        assert manager.contains_key(REGION, "k") is False

    def test_slow_loader_does_not_block_other_keys(self) -> None:
        manager = _manager()
        started = threading.Event()

        def slow(key: str) -> object:
            if key == "slow":
                started.set()
                time.sleep(0.2)
            return key

        manager.register_loader(REGION, slow)

        worker = threading.Thread(target=lambda: manager.get(REGION, "slow"))
        worker.start()
        assert started.wait(timeout=2)
        assert manager.get(REGION, "fast") == "fast"
        worker.join(timeout=5)
