"""Sentinel ResourceRegistry(M1.4)。

中文
----
``ResourceRegistry`` 维护 Engine 已知的 ``Resource`` 集合,支持
``max_resources`` 限流 + ``idle_ttl`` 自动清理 + ``overflow`` 事件。

设计要点:

- **last_access_ns**:每次 ``get_or_create`` 更新;``idle_ttl`` 过期
  且 current_access 之前的 Resource 在 cleanup 时被删
- **overflow policy**:
  - ``OverflowPolicy.ERROR`` — 抛 ``SentinelConfigurationError``
  - ``OverflowPolicy.EVICT_OLDEST`` — 删最久未访问的(M1.4 默认)
- **不存储 Resource 内部数据**:只存 ``Resource`` 对象本身,``attrs``
  等字段由调用方持有

English
--------
Sentinel ResourceRegistry (M1.4).

``ResourceRegistry`` maintains the set of ``Resource``s known to the
Engine, supporting ``max_resources`` capping, ``idle_ttl`` auto
cleanup, and ``overflow`` events.

Design points:

- **last_access_ns** — updated on each ``get_or_create``; resources
  whose last access is older than ``idle_ttl`` are removed during
  cleanup.
- **Overflow policy**:
  - ``OverflowPolicy.ERROR`` — raise ``SentinelConfigurationError``.
  - ``OverflowPolicy.EVICT_OLDEST`` — drop least-recently-used (M1.4
    default).
- **Does not store Resource internals** — only the ``Resource``
  object itself; ``attrs`` etc. are held by the caller."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..errors import SentinelConfigurationError
from ..model.resource import Resource

if TYPE_CHECKING:
    from ..primitives.clock import Clock


class OverflowPolicy(enum.Enum):
    """中文
    ----
    超过 ``max_resources`` 时的处理策略。

    English
    --------
    Policy when ``max_resources`` is exceeded.
    """

    ERROR = "error"              # 抛 SentinelConfigurationError
    EVICT_OLDEST = "evict_oldest"  # 删最久未访问的(M1.4 默认)


@dataclass(slots=True)
class _Entry:
    """中文
    ----
    ResourceRegistry 内部条目(只跟 ResourceRegistry 自身相关,
    与 metrics 无关)。

    English
    --------
    ResourceRegistry internal entry (only relevant to ResourceRegistry;
    metrics live in MetricRegistry).
    """

    resource: Resource
    last_access_ns: int


class ResourceRegistry:
    """中文
    ----
    Engine 已知的 Resource 集合。

    English
    --------
    Set of resources known to the Engine.
    """

    def __init__(
        self,
        *,
        max_resources: int = 10_000,
        idle_ttl_ns: int = 0,  # 0 = 永不清理
        overflow: OverflowPolicy = OverflowPolicy.EVICT_OLDEST,
    ) -> None:
        if max_resources <= 0:
            raise ValueError(f"max_resources must be positive (got {max_resources})")
        if idle_ttl_ns < 0:
            raise ValueError(f"idle_ttl_ns must be non-negative (got {idle_ttl_ns})")
        self.max_resources = max_resources
        self.idle_ttl_ns = idle_ttl_ns
        self.overflow = overflow
        self._entries: dict[str, _Entry] = {}

    def _now_ns(self) -> int:
        return time.time_ns()

    def get_or_create(
        self,
        resource: Resource,
        *,
        clock_ns: int | None = None,
    ) -> Resource:
        """中文
        ----
        获取或注册一个 Resource。

        - 已存在:更新 last_access_ns,返回原 Resource(不变)
        - 不存在:按 ``overflow`` 策略处理;``EVICT_OLDEST`` 时
          删最久未访问的,新 Resource 占用

        English
        --------
        Get or register a Resource.

        - Already present: update last_access_ns, return existing
          (unchanged) Resource.
        - New: apply ``overflow`` policy; ``EVICT_OLDEST`` removes
          the least-recently-used one and registers the new Resource.
        """
        now = clock_ns if clock_ns is not None else self._now_ns()
        existing = self._entries.get(resource.name)
        if existing is not None:
            existing.last_access_ns = now
            return existing.resource
        # New registration
        if len(self._entries) >= self.max_resources:
            if self.overflow is OverflowPolicy.ERROR:
                raise SentinelConfigurationError(
                    f"ResourceRegistry exceeded max_resources={self.max_resources}",
                    field="resource_registry",
                    reason="max_resources_exceeded",
                    value=resource.name,
                )
            # EVICT_OLDEST: drop least-recently-accessed
            victim_name = min(
                self._entries,
                key=lambda n: self._entries[n].last_access_ns,
            )
            del self._entries[victim_name]
        self._entries[resource.name] = _Entry(resource=resource, last_access_ns=now)
        return resource

    def cleanup(self, *, clock_ns: int | None = None) -> int:
        """中文
        ----
        删除 idle_ttl_ns 之前未访问的 Resource;返回删除数。

        English
        --------
        Remove resources not accessed within ``idle_ttl_ns``; return
        the count removed.
        """
        if self.idle_ttl_ns == 0:
            return 0
        now = clock_ns if clock_ns is not None else self._now_ns()
        threshold = now - self.idle_ttl_ns
        to_delete = [
            name for name, e in self._entries.items() if e.last_access_ns < threshold
        ]
        for name in to_delete:
            del self._entries[name]
        return len(to_delete)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def __iter__(self):
        return iter(e.resource for e in self._entries.values())


__all__ = ["ResourceRegistry", "OverflowPolicy"]
