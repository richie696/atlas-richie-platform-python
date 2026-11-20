"""降级策略注册表（对位 Java `DegradeStrategyRegistry` / `DefaultDegradeStrategyRegistry`）。

按 `order` 升序（同名再按 `name`）排序，取第一个 `matches()` 为真的策略。
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from .model import DegradeStrategy, Trigger


@runtime_checkable
class DegradeStrategyRegistry(Protocol):
    """降级策略注册表（对位 Java 同名接口）。"""

    def register(self, name: str, strategy: DegradeStrategy) -> None:
        """注册一个策略（同名覆盖）。"""
        ...

    def unregister(self, name: str) -> None:
        """取消注册。"""
        ...

    def select(self, trigger: Trigger | None) -> DegradeStrategy | None:
        """按触发条件选首个匹配策略；无命中返回 None。"""
        ...

    def all(self) -> list[DegradeStrategy]:
        """全部已注册策略（按 order 升序），用于诊断。"""
        ...


class DefaultDegradeStrategyRegistry:
    """默认注册表实现（对位 Java `DefaultDegradeStrategyRegistry`）。

    内部维护：`name → strategy` 的映射 + 按 `order` 升序的快照。`register` /
    `unregister` 时重排快照，`select` 在快照上遍历（O(N)）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, DegradeStrategy] = {}
        self._sorted: tuple[DegradeStrategy, ...] = ()

    def register(self, name: str, strategy: DegradeStrategy) -> None:
        if not name or not name.strip():
            raise ValueError("name must not be blank")
        if strategy is None:
            raise ValueError("strategy must not be None")
        with self._lock:
            self._by_name[name] = strategy
            self._rebuild()

    def unregister(self, name: str) -> None:
        with self._lock:
            if self._by_name.pop(name, None) is not None:
                self._rebuild()

    def select(self, trigger: Trigger | None) -> DegradeStrategy | None:
        with self._lock:
            candidates = self._sorted
        for strategy in candidates:
            if strategy.matches(trigger):
                return strategy
        return None

    def all(self) -> list[DegradeStrategy]:
        with self._lock:
            return list(self._sorted)

    def names(self) -> tuple[str, ...]:
        """已注册的策略名（诊断用）。"""
        with self._lock:
            return tuple(sorted(self._by_name))

    def _rebuild(self) -> None:
        strategies = list(self._by_name.values())
        strategies.sort(key=lambda item: (item.order(), item.name()))
        self._sorted = tuple(strategies)


__all__ = ["DefaultDegradeStrategyRegistry", "DegradeStrategyRegistry"]
