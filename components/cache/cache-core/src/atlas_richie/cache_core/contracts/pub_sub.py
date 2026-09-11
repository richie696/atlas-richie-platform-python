"""Pub/Sub 通知操作接口。
----
发布订阅（Pub/Sub）通知操作接口。
提供基于 Redis Pub/Sub 的通知能力，用于轻量级消息发布。

English
--------
Pub/Sub bus contract.

Mirrors `cn.richie696.component.cache.ops.NotificationOps` plus the
Java `redis.manage.RedisNotificationManager` shape.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Protocol


class PubSubBus(Protocol):
    """发布订阅（Pub/Sub）通知操作接口。

    提供基于 Redis Pub/Sub 的通知能力，用于轻量级消息发布。
    契约刻意保持最小化：仅 `publish`。
    订阅者管理由实现中注册的 `MessageListener` 回调负责。

    English
    --------
    Mirrors `ops/NotificationOps.java`. The contract is intentionally
    minimal: `publish` only. Subscriber management is via the
    `MessageListener` callback registered in implementations.
    """

    @abstractmethod
    def publish(self, topic: str, message: Any) -> int:
        """发布到 topic，返回订阅者数量。

        English
        --------
        Publish to topic; return the number of subscribers.
        """
        ...


__all__ = ["PubSubBus"]
