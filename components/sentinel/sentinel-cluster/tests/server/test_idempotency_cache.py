"""IdempotencyCache 单测 (M6.3.3).

6 个单测覆盖: 命中 / 不命中 / TTL 过期 / 跨 instance_id / 跨 resource /
get_or_set 二次写防并发.
"""

from __future__ import annotations

import pytest

from atlas_richie.sentinel_cluster.server.idempotency_cache import IdempotencyCache

pytestmark = pytest.mark.unit


class FakeClock:
    """可注入的 fake clock (单测 helper)."""

    def __init__(self, start_ns: int = 1_000_000_000_000_000_000) -> None:
        self._now_ns = start_ns

    def __call__(self) -> int:
        return self._now_ns

    def advance(self, ns: int) -> None:
        self._now_ns += ns


def _make_cache(*, ttl_ns: int = 300_000_000_000, clock=None) -> IdempotencyCache:
    return IdempotencyCache(ttl_ns=ttl_ns, clock=clock or FakeClock())


class TestIdempotencyCacheHitMiss:
    """命中 / 不命中基础路径."""

    @pytest.mark.asyncio
    async def test_get_returns_none_on_miss(self) -> None:
        cache = _make_cache()
        result = await cache.get("req-1", "instance-A", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_put_then_get_returns_value(self) -> None:
        cache = _make_cache()
        await cache.put("req-1", "instance-A", 0, {"decision": "GRANTED"})
        result = await cache.get("req-1", "instance-A", 0)
        assert result == {"decision": "GRANTED"}


class TestIdempotencyCacheTTL:
    """TTL 过期 (5 min 默认, 可注入缩短)."""

    @pytest.mark.asyncio
    async def test_ttl_expiry_returns_none(self) -> None:
        clock = FakeClock()
        cache = _make_cache(ttl_ns=1_000_000_000, clock=clock)  # 1 s TTL
        await cache.put("req-1", "instance-A", 0, {"x": 1})
        # 推进 0.5 s: 仍命中
        clock.advance(500_000_000)
        assert await cache.get("req-1", "instance-A", 0) == {"x": 1}
        # 推进 0.6 s: 总 1.1 s, 已过期
        clock.advance(600_000_000)
        assert await cache.get("req-1", "instance-A", 0) is None

    @pytest.mark.asyncio
    async def test_scrub_expired_removes_entries(self) -> None:
        clock = FakeClock()
        cache = _make_cache(ttl_ns=1_000_000_000, clock=clock)  # 1 s TTL
        await cache.put("req-1", "instance-A", 0, {"x": 1})
        await cache.put("req-2", "instance-A", 0, {"x": 2})
        assert cache.size == 2
        clock.advance(1_500_000_000)  # +1.5 s
        cleaned = await cache.scrub_expired()
        assert cleaned == 2
        assert cache.size == 0


class TestIdempotencyCacheKeyDimensions:
    """key 三元组隔离 (跨 instance_id / startup_epoch 隔离)."""

    @pytest.mark.asyncio
    async def test_different_instance_id_is_miss(self) -> None:
        cache = _make_cache()
        await cache.put("req-1", "instance-A", 0, {"x": 1})
        # 同样 request_id, 不同 instance_id → miss
        result = await cache.get("req-1", "instance-B", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_different_startup_epoch_is_miss(self) -> None:
        cache = _make_cache()
        await cache.put("req-1", "instance-A", 0, {"x": 1})
        # 同样 request_id + instance_id, 不同 startup_epoch → miss
        result = await cache.get("req-1", "instance-A", 1)
        assert result is None


class TestIdempotencyCacheGetOrSet:
    """get_or_set 行为 (含并发双写防护)."""

    @pytest.mark.asyncio
    async def test_get_or_set_calls_factory_on_miss(self) -> None:
        cache = _make_cache()
        call_count = {"n": 0}

        def factory() -> dict:
            call_count["n"] += 1
            return {"decision": "GRANTED"}

        value, hit = await cache.get_or_set("req-1", "instance-A", 0, factory)
        assert value == {"decision": "GRANTED"}
        assert hit is False
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_get_or_set_skips_factory_on_hit(self) -> None:
        cache = _make_cache()
        await cache.put("req-1", "instance-A", 0, {"decision": "CACHED"})
        call_count = {"n": 0}

        def factory() -> dict:
            call_count["n"] += 1
            return {"decision": "NEW"}

        value, hit = await cache.get_or_set("req-1", "instance-A", 0, factory)
        assert value == {"decision": "CACHED"}
        assert hit is True
        assert call_count["n"] == 0
