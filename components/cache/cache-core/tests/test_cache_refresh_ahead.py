"""L1 refresh-ahead contract tests.

Refresh-ahead reloads entries that are close to expiry through the
read-through loader, so a hot key does not pay a source round-trip at the
moment it expires.

Covers: the candidate window, the refreshed value, the sliding expiry, the
"already expired is not refreshed" rule, the read-through + loader
requirement, and shutdown.

The expiry timeline is driven by `ManualClock`, so the window boundaries
are exact instead of sleep-dependent; only the scanner's poll interval
uses real time.
"""

from __future__ import annotations

import time

import pytest

from atlas_richie.cache_core.local import (
    CacheDefinition,
    ExpiryPolicy,
    LocalCacheManager,
    LocalCacheProperties,
)

pytestmark = pytest.mark.unit

REGION = "refresh-ahead-region"


class _CountingLoader:
    def __init__(self) -> None:
        self.calls = 0

    def load(self, key: str) -> object:
        self.calls += 1
        return f"value-{self.calls}"

    def load_all(self, keys):
        return {key: self.load(key) for key in keys}


@pytest.fixture
def clock(monkeypatch):
    """Deterministic millisecond clock for the expiry timeline."""
    from atlas_richie.testing import ManualClock

    from atlas_richie.cache_core.local.manage import local_cache_manager as lcm

    manual = ManualClock()
    monkeypatch.setattr(
        lcm._CacheBucket, "_now_millis", staticmethod(lambda: int(manual()))
    )
    return manual


def _manager(
    *,
    ttl_millis: int = 400,
    ratio: float = 0.5,
    threads: int = 1,
    read_through: bool = True,
    refresh_ahead: bool = True,
) -> LocalCacheManager:
    definition = CacheDefinition(
        expiry_policy=ExpiryPolicy.CREATED,
        ttl_millis=ttl_millis,
        refresh_ahead=refresh_ahead,
        refresh_ahead_ratio=ratio,
        refresh_ahead_threads=threads,
        read_through=read_through,
        statistics_enabled=True,
    )
    return LocalCacheManager(
        properties=LocalCacheProperties(cache_definitions={REGION: definition}),
        refresh_ahead_scan_interval_seconds=0.01,
    )


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestRefreshAhead:
    def test_entry_close_to_expiry_is_refreshed(self, clock) -> None:
        manager = _manager(ttl_millis=400, ratio=0.5)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(300)   # remaining 100 <= 400 * 0.5
        assert _wait_until(lambda: loader.calls >= 1), "the entry was not refreshed"
        assert manager.get(REGION, "k") == "value-1"

    def test_refresh_slides_the_expiry_forward(self, clock) -> None:
        """The refresh keeps the original TTL *duration*, not the old deadline."""
        manager = _manager(ttl_millis=400, ratio=0.5)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")
        assert manager._bucket(REGION)._expiries["k"] == 400

        clock.set(300)
        assert _wait_until(lambda: loader.calls >= 1)

        bucket = manager._bucket(REGION)
        assert bucket._ttls["k"] == 400, "the original TTL duration is kept"
        assert bucket._expiries["k"] == 700, "the deadline slid forward by 400 ms"

    def test_refreshed_value_is_served_without_a_new_load(self, clock) -> None:
        manager = _manager(ttl_millis=400, ratio=0.5)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(300)
        assert _wait_until(lambda: loader.calls >= 1)

        assert manager.get(REGION, "k") == "value-1"
        assert loader.calls == 1, "the refreshed value is already cached"

    def test_expired_entry_is_not_refreshed(self, clock) -> None:
        manager = _manager(ttl_millis=400, ratio=0.5)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(500)   # already past the 400 ms deadline
        time.sleep(0.15)
        assert loader.calls == 0, "an expired entry is reloaded by the next read"

    def test_entry_outside_the_window_is_not_refreshed(self, clock) -> None:
        manager = _manager(ttl_millis=400, ratio=0.5)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(100)   # remaining 300 > 400 * 0.5
        time.sleep(0.15)
        assert loader.calls == 0

    def test_refresh_requires_a_loader(self, clock) -> None:
        manager = _manager()
        manager.put(REGION, "k", "stale")

        clock.set(300)
        time.sleep(0.15)
        assert manager.get(REGION, "k") == "stale", "no loader, no refresh"

    def test_refresh_requires_read_through(self, clock) -> None:
        """Java: the refresh-ahead switch only works together with readThrough."""
        manager = _manager(read_through=False)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(300)
        time.sleep(0.15)
        assert loader.calls == 0

    def test_refresh_ahead_disabled_never_refreshes(self, clock) -> None:
        manager = _manager(refresh_ahead=False)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(300)
        time.sleep(0.15)
        assert loader.calls == 0

    def test_close_stops_the_refresh_thread(self, clock) -> None:
        manager = _manager()
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        clock.set(300)
        assert _wait_until(lambda: loader.calls >= 1)

        manager.close()
        calls_after_close = loader.calls
        time.sleep(0.15)

        assert loader.calls == calls_after_close
        assert manager.size(REGION) == 0

    def test_refresh_ahead_thread_count_is_configurable(self) -> None:
        manager = _manager(threads=3)
        loader = _CountingLoader()
        manager.register_loader(REGION, loader)
        manager.put(REGION, "k", "stale")

        assert manager._refresh_executors[REGION]._max_workers == 3

    def test_refresh_failure_leaves_the_entry_alone(self, clock) -> None:
        manager = _manager()
        manager.register_loader(REGION, lambda key: (_ for _ in ()).throw(RuntimeError))
        manager.put(REGION, "k", "stale")

        clock.set(300)
        time.sleep(0.15)
        assert manager.get(REGION, "k") == "stale"
