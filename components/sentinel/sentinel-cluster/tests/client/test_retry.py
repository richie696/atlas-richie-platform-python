"""Client 重试策略单测 (M6.3.4) — 3 个测试.

中文
----
- ``test_backoff_schedule_3_attempts``: 验证 50ms / 200ms / 1s 退避序列
- ``test_should_retry_bounds``: 验证 should_retry 边界
- ``test_total_backoff_1_5s``: 验证 3 次 retry 总耗时 ≈ 1.25s

English
--------
- ``test_backoff_schedule_3_attempts``: verify 50ms / 200ms / 1s backoff schedule
- ``test_should_retry_bounds``: verify should_retry boundaries
- ``test_total_backoff_1_5s``: verify 3 retries total ≈ 1.25s
"""

from __future__ import annotations

import asyncio
import time

import pytest

from atlas_richie.sentinel_cluster.client.retry import (
    MAX_RETRIES,
    backoff_for_attempt,
    should_retry,
)

pytestmark = pytest.mark.unit


class TestBackoffSchedule:
    """3 次 exponential backoff 序列 (50ms / 200ms / 1s)."""

    def test_backoff_schedule_3_attempts(self) -> None:
        # IMPLEMENTATION-PLAN §1.1 决策: 50ms / 200ms / 1s
        assert backoff_for_attempt(0) == pytest.approx(0.05, abs=1e-6)
        assert backoff_for_attempt(1) == pytest.approx(0.20, abs=1e-6)
        assert backoff_for_attempt(2) == pytest.approx(1.00, abs=1e-6)

    def test_backoff_attempt_3_returns_zero(self) -> None:
        # attempt == MAX_RETRIES (3) 不再 retry, 返回 0
        assert backoff_for_attempt(3) == 0.0

    def test_backoff_negative_attempt_raises(self) -> None:
        # 防御性: 负数 attempt 抛 ValueError
        with pytest.raises(ValueError, match="attempt must be in"):
            backoff_for_attempt(-1)

    def test_backoff_out_of_range_raises(self) -> None:
        # 防御性: 越界 attempt 抛 ValueError
        with pytest.raises(ValueError, match="attempt must be in"):
            backoff_for_attempt(4)


class TestShouldRetry:
    """should_retry 边界检查."""

    def test_should_retry_bounds(self) -> None:
        # 0 / 1 / 2 → True (3 次 retry 机会)
        assert should_retry(0) is True
        assert should_retry(1) is True
        assert should_retry(2) is True
        # 3 → False (已用完 retry 预算)
        assert should_retry(3) is False
        # 负数 / 越界 → False (防御性)
        assert should_retry(-1) is False
        assert should_retry(4) is False

    def test_max_retries_constant(self) -> None:
        # 防御性: MAX_RETRIES 永远是 3 (协议 / IMPLEMENTATION-PLAN §1.1 冻结)
        assert MAX_RETRIES == 3


class TestBackoffTotal:
    """总退避耗时 ≤ 1.5s (M6.3.4 决策)."""

    def test_total_backoff_under_1_5s(self) -> None:
        # 3 次 backoff 总和: 0.05 + 0.20 + 1.00 = 1.25s ≤ 1.5s
        total = sum(backoff_for_attempt(i) for i in range(MAX_RETRIES))
        assert total == pytest.approx(1.25, abs=1e-6)
        assert total < 1.5  # 跟 IMPLEMENTATION-PLAN §1.1 决策一致

    @pytest.mark.asyncio
    async def test_async_sleep_total_under_1_5s(self) -> None:
        # 真实 asyncio.sleep 总耗时验证 (防止有人偷偷把 sleep 改成 0)
        start = time.perf_counter()
        for i in range(MAX_RETRIES):
            await asyncio.sleep(backoff_for_attempt(i))
        elapsed = time.perf_counter() - start
        # 留 50ms 缓冲 (pytest 调度 / system clock)
        assert elapsed < 1.5
        # 但又应该 > 1.2s (确保 sleep 真发生, 不是 noop)
        assert elapsed > 1.2
