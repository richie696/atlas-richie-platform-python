"""注入式随机源,贯穿所有 Sentinel 原语(尤其 retry jitter)。
----
`RandomSource` 在 M0.5 之前位于 `atlas_richie.resilience.clock`;M0.5
按目标结构拆出到独立模块,让 `Clock` 只负责时间、`RandomSource` 只
负责随机数,职责分离更清晰。

- **RandomSource**:可重现的均匀分布接口。
- **SystemRandom**:默认实现,底层 `random.uniform`。
- **DeterministicRandom**:总是返回固定中点,便于 jitter 测试断言。

English
--------
Injectable random source used by every Sentinel primitive (notably
retry jitter).

`RandomSource` was originally colocated with `Clock` inside
`atlas_richie.resilience.clock`. The M0.5 migration split it out so
`Clock` owns time and `RandomSource` owns randomness — single
responsibility per module.

- **RandomSource** — reproducible uniform-distribution interface.
- **SystemRandom** — default impl backed by `random.uniform`.
- **DeterministicRandom** — fixed midpoint, for deterministic tests."""

from __future__ import annotations

import random
from typing import Protocol


class RandomSource(Protocol):
    """中文
    ----
    可重现的随机源,用于 retry jitter 等需要可控随机性的场景。

    English
    --------
    A reproducible random source used by retry jitter and similar features.
    """

    def uniform(self, low: float, high: float) -> float:
        """中文
        ----
        返回 `[low, high)` 区间内均匀分布的随机数。

        English
        --------
        Return a uniformly distributed value in `[low, high)`.
        """


class SystemRandom:
    """中文
    ----
    默认 `RandomSource` 实现,底层使用 `random.uniform`。

    English
    --------
    The default `RandomSource`; backed by `random.uniform`.
    """

    def uniform(self, low: float, high: float) -> float:
        return random.uniform(low, high)


class DeterministicRandom:
    """中文
    ----
    始终返回固定中点的 `RandomSource`,用于确定性测试。

    English
    --------
    A `RandomSource` that returns a fixed midpoint, for deterministic tests.
    """

    def __init__(self, value: float = 0.5) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("DeterministicRandom value must be in [0.0, 1.0]")
        self._value = value

    def uniform(self, low: float, high: float) -> float:
        return low + (high - low) * self._value
