"""Sentinel Slot 决策 / 租约(进入与释放的对称抽象)。

中文
----
Slot 拒绝时抛 SentinelBlockedError;放行时返回 ``SlotLease``(Protocol),
Engine 持有 lease 直至 entry 完成,entry 退出时**逆序**调用每个 Slot 的
release(对应 Lease)。``NoopSlotLease`` 用于不放行也不拒绝的占位场景
(例如 ParamFlowSlot 跳过非热点资源)。

设计要点:

- **Protocol + frozen 不可变** ``NoopSlotLease`` 双轨:动态类型 Slot 用
  Protocol,Engine 自身用 frozen 值
- **release 幂等**:Slot 实现必须保证 ``release()`` 可被 Engine 多次
  调用而不重复释放或抛错
- **可丢弃(``__enter__`` + ``__exit__``)**:便于 ``async with`` 风格
  集成,但 Sentinel Engine 走显式 ``acquire`` / ``release``,不走 ctx
  manager(详见 M1.2 SlotChain 语义)

English
--------
Slot decision / lease — symmetric abstraction for entry and release.

When a Slot rejects, it raises ``SentinelBlockedError``; when it admits,
it returns a ``SlotLease`` (Protocol). The Engine holds the lease until
entry completion, then calls each Slot's release in **reverse order**
at exit. ``NoopSlotLease`` is the placeholder for Slots that neither
admit nor reject (e.g. ParamFlowSlot skipping a non-hot-spot resource).

Design points:

- **Protocol + frozen-immutable** ``NoopSlotLease`` two-track: dynamic
  Slot implementations use Protocol, the Engine uses frozen values.
- **release idempotency** — Slot implementations must tolerate multiple
  ``release()`` calls without double-release or errors.
- **droppable (``__enter__`` / ``__exit__``)** — available for
  ``async with`` integration, but the Sentinel Engine uses explicit
  ``acquire`` / ``release``, not context managers (see M1.2 SlotChain
  semantics)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .resource import Resource


@runtime_checkable
class SlotLease(Protocol):
    """中文
    ----
    Slot 放行后交给 Engine 的租约句柄。

    Slot 实现必须满足:

    - ``resource`` 属性:返回该 lease 关联的 Resource
    - ``release()`` 协程:Engine 退出时调用,**必须幂等**
    - 可选 ``__aenter__`` / ``__aexit__``(用于 ``async with``,非必需)

    English
    --------
    Lease handle that a Slot hands to the Engine on admission.

    Slot implementations must satisfy:

    - ``resource`` attribute — Resource this lease is bound to.
    - ``release()`` coroutine — called by the Engine at exit; **must be
      idempotent**.
    - Optional ``__aenter__`` / ``__aexit__`` (for ``async with``
      sugar; not required).
    """

    @property
    def resource(self) -> Resource:
        ...

    async def release(self) -> None:
        ...


@dataclass(frozen=True, slots=True)
class NoopSlotLease:
    """中文
    ----
    不分配任何资源的占位 lease。ParamFlowSlot 跳过非热点资源、或 Slot
    实现不持有任何需要释放的状态时,返回它。

    ``release()`` 什么都不做;``resource`` 返回构造时给定的 Resource
    (用于一致性 + 错误日志)。

    English
    --------
    Placeholder lease that does not hold any resource. Returned when
    ``ParamFlowSlot`` skips a non-hot-spot resource, or when a Slot
    implementation has nothing to release.

    ``release()`` is a no-op; ``resource`` returns the Resource given
    at construction (for consistency + error logging).
    """

    resource: Resource

    async def release(self) -> None:
        """中文
        ----
        什么都不做;Engine 多次调用也安全。

        English
        --------
        No-op; safe to call multiple times.
        """
        return None


__all__ = ["SlotLease", "NoopSlotLease"]
