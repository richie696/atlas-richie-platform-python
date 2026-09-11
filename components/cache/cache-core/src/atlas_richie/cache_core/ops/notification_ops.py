"""发布订阅（Pub/Sub）通知操作接口。

中文
----
发布订阅（Pub/Sub）通知操作接口。
提供基于 Redis Pub/Sub 的通知能力，用于轻量级消息发布。

@author richie696
@version 1.0.0
@since 2025-06-05

English
--------
Pub/Sub notification ops interface.

Mirrors `cn.richie696.component.cache.ops.NotificationOps`.

`subscribe` is part of the contract because the lifecycle of a
subscription (open → deliver → close) is identical across all
backends; only the wire format differs. Backends implement this
on top of Redis Pub/Sub, Kafka, RabbitMQ, etc.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Callable, Protocol

from ..contracts.notification_listener import NotificationListener


class NotificationOps(Protocol):
    """中文
    ----
    发布订阅（Pub/Sub）通知操作接口。

    English
    --------
    Pub/Sub notification operations interface. Mirrors
    `ops/NotificationOps.java`. Suitable for lightweight message
    publication + subscription.

    `subscribe` is part of the contract because the lifecycle of a
    subscription (open → deliver → close) is identical across all
    backends; only the wire format differs. Backends implement this
    on top of Redis Pub/Sub, Kafka, RabbitMQ, etc.
    """

    @abstractmethod
    def publish(self, topic: str, message: Any) -> int:
        """中文
        ----
        发布到 topic，返回订阅者数量。

        English
        --------
        Publish to topic; returns the number of subscribers that
        received the message.
        """
        ...

    @abstractmethod
    def subscribe(
        self,
        topic: str,
        handler: Callable[[str, Any], None],
    ) -> NotificationListener:
        """中文
        ----
        订阅一个 topic。

        Args:
            topic: 频道名（所有后端都用相同的字符串空间 — caller 负责
                加 namespace 前缀）。
            handler: 异步消息回调，签名 `(channel, message) -> None`。
                handler 抛异常会被记录但不会中断订阅。

        Returns:
            `NotificationListener` 句柄；caller 用完调 `close()` 释放。

        English
        --------
        Subscribe to a topic.

        Args:
            topic: Channel name (all backends share the same string
                space — the caller is responsible for adding the
                namespace prefix).
            handler: Async message callback, signature
                `(channel, message) -> None`. Exceptions raised by
                the handler are logged but do not stop the
                subscription.

        Returns:
            A `NotificationListener` handle; the caller must call
            `close()` to release it.
        """
        ...


__all__ = ["NotificationOps"]
