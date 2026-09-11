"""Pub/Sub 订阅句柄接口。
----
Pub/Sub 订阅句柄契约。`subscribe()` 调用返回一个
`NotificationListener`，调用方在订阅激活期间持有该句柄，
完成后调用 `close()` 关闭。

English
--------
Pub/Sub subscription handle contract.

Mirrors the lifecycle of `cn.richie696.component.cache.redis.bean.NotificationBus`
in Java: a `subscribe()` call returns a `NotificationListener` that the
caller holds while the subscription is active and `close()`s when done.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationListener(Protocol):
    """单条 Pub/Sub 订阅的句柄。

    生命周期：由 `NotificationOps.subscribe(...)` 创建，
    在后端拥有的线程上异步投递消息，调用方在不再需要时关闭。
    同一 topic 上可并存多个 listener（每条消息都会获得自己的副本）。

    English
    --------
    A handle to a single Pub/Sub subscription.

    Lifecycle: the listener is created by `NotificationOps.subscribe(...)`,
    delivers messages asynchronously on a backend-owned thread, and is
    closed by the caller when no longer needed. Multiple listeners may
    coexist for the same topic (each gets its own copy of every message).
    """

    @abstractmethod
    def is_open(self) -> bool:
        """订阅是否仍然处于激活状态并正在投递消息。

        English
        --------
        Whether the subscription is still active and delivering messages.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """停止订阅并释放后端资源。

        幂等：对已关闭的 listener 调用 `close()` 是 no-op。

        English
        --------
        Stop the subscription and release backend resources.

        Idempotent: calling `close()` on an already-closed listener
        is a no-op.
        """
        ...


__all__ = ["NotificationListener"]
