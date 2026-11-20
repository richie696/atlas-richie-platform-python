"""`4.6 热更新注册表（对位 Java `HotReloadRegistry` / `DefaultHotReloadRegistry`）。

`4.6.9 不依赖任何配置中心：本表只提供「被调」接口，业务方自行接 Nacos / 云
`4.6.10 配置中心后调 `reload` / `reload_all`。
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable

from ..hook import HookBus
from .model import ReloadEvent, Reloadable


@runtime_checkable
class HotReloadRegistry(Protocol):
    """`4.6.11 热更新注册表。"""

    def register(self, name: str, reloadable: Reloadable) -> None:
        """`4.6.12 注册一个可热替换对象（同名覆盖）。"""
        ...

    def unregister(self, name: str) -> None:
        """`4.6.13 取消注册。"""
        ...

    def get(self, name: str) -> Reloadable | None:
        """`4.6.14 获取当前注册的 Reloadable。"""
        ...

    def names(self) -> frozenset[str]:
        """`4.6.15 全部已注册名（用于诊断 / reload_all）。"""
        ...

    def reload(self, name: str) -> bool:
        """`4.6.16 重载单个对象；返回 True 表示成功。"""
        ...

    def reload_all(self) -> int:
        """`4.6.17 重载全部（配置中心全量刷新场景）；返回成功数量。"""
        ...


class DefaultHotReloadRegistry:
    """`4.6.18 默认热更新注册表实现。

    `4.6.19 线程安全（注册表由锁保护）；`reload` 时若传入 `HookBus`，自动发布
    `4.6.20。
    """

    def __init__(self, hook_bus: HookBus | None = None) -> None:
        self._lock = threading.Lock()
        self._reloadables: dict[str, Reloadable] = {}
        self._hook_bus = hook_bus

    def register(self, name: str, reloadable: Reloadable) -> None:
        if not name or not name.strip():
            raise ValueError("name must not be blank")
        if reloadable is None:
            raise ValueError("reloadable must not be None")
        with self._lock:
            self._reloadables[name] = reloadable

    def unregister(self, name: str) -> None:
        with self._lock:
            self._reloadables.pop(name, None)

    def get(self, name: str) -> Reloadable | None:
        with self._lock:
            return self._reloadables.get(name)

    def names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._reloadables)

    def reload(self, name: str) -> bool:
        with self._lock:
            reloadable = self._reloadables.get(name)
        if reloadable is None:
            return False
        self._trigger_accept(reloadable)
        self._publish(name)
        return True

    def reload_all(self) -> int:
        count = 0
        for name in sorted(self.names()):
            if self.reload(name):
                count += 1
        return count

    @staticmethod
    def _trigger_accept(reloadable: Reloadable) -> None:
        state = reloadable.current_state()
        reloadable.accept(state)

    def _publish(self, name: str) -> None:
        if self._hook_bus is None:
            return
        try:
            self._hook_bus.publish(ReloadEvent.of(name))
        except Exception:  # noqa: BLE001 — 事件发布失败不得影响重载本身
            return


__all__ = ["DefaultHotReloadRegistry", "HotReloadRegistry"]
