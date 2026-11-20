"""`4.6 热更新契约（对位 Java `web.core.reload` 的 `Reloadable` / `ReloadEvent`）。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

from ..hook import HookEvent

StateT = TypeVar("StateT")


@runtime_checkable
class Reloadable(Protocol):
    """`4.6.1 可热替换对象。

    `4.6.2 实现必须是幂等的（重复调用效果相同）+ 线程安全（其他线程可能同时
    `4.6.3 正在读 `current_state`）。

    `4.6.6 `name()` 是**可选**的——对位 Java 的 `default String name()`（默认取
    类名）。不实现时注册表用 `reloadable_name()` 兜底。
    """

    def current_state(self) -> StateT:
        """`4.6.4 当前状态（用于 diff / 校验）。"""
        ...

    def accept(self, new_state: StateT) -> None:
        """`4.6.5 应用新状态。"""
        ...


def reloadable_name(reloadable: object) -> str:
    """注册名（对位 Java `Reloadable.name()` 的默认实现：类名）。

    `4.6.6.1 实现方自定义了 `name()` 就用它，否则回落到类名——与 Java 的
    `default` 方法同语义。
    """
    candidate = getattr(reloadable, "name", None)
    if callable(candidate):
        resolved = candidate()
        if resolved:
            return str(resolved)
    return type(reloadable).__name__


@dataclass(frozen=True, slots=True)
class ReloadEvent(HookEvent):
    """`4.6.7 配置重载事件。"""

    name: str
    timestamp: float

    @classmethod
    def of(cls, name: str) -> "ReloadEvent":
        """`4.6.8 构造重载事件（时间戳为当前墙钟秒）。"""
        return cls(name=name, timestamp=time.time())


__all__ = ["ReloadEvent", "Reloadable", "reloadable_name"]
