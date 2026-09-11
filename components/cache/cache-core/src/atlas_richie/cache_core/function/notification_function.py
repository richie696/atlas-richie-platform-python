"""发布通知 API 函数。
----
发布通知 API 管理器接口，封装了基于 Redis 发布订阅（Pub/Sub）机制的通知功能。

**与 Stream 消息队列的区别：**
- **发布订阅（convertAndSend）**：基于 Redis 的 Pub/Sub 机制，消息只在内存中，
  只有在线订阅者能收到，离线后消息丢失，无持久化、无消费确认，
  适合事件通知、在线推送等场景。
- **Stream 消息队列**：基于 Redis Stream 数据结构，消息持久化存储，
  支持消费组、消息确认、消息堆积和回溯，适合可靠消息、异步任务、
  日志收集等场景。

**本接口只封装了发布订阅（Pub/Sub）机制，适用于在线通知、推送、
事件广播等对可靠性要求不高的场景。**
若需可靠消息、消费确认、消息堆积等能力，请使用 Redis Stream 管理器。

English
--------
Pub/Sub publish notification function (high-level, built on `NotificationOps`).

Mirrors `cn.richie696.component.cache.function.NotificationFunction`.
Only the publish-side is exposed; subscription management is owned by
the backend (Redis Pub/Sub, Kafka, RabbitMQ, etc.) and not part of the
core abstraction.

**Pub/Sub vs Stream**: Pub/Sub is fire-and-forget, no persistence, no
ack — suitable for online event broadcast / push. For reliable
queueing with ack + replay, use the dedicated Stream-MQ module instead.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol


class NotificationFunction(Protocol):
    """发布通知 API。

    基于发布订阅机制，适用于在线通知、事件广播等对可靠性要求不高的场景。
    若需可靠消息、消费确认、消息堆积等能力，请使用 Stream 消息队列。

    English
    --------
    基于发布订阅机制，适用于在线通知、事件广播等对可靠性要求不高的场景。
    """

    @abstractmethod
    def publish_notify(self, topic: str, message: Any) -> int:
        """发布消息到指定频道。

        Args:
            topic: 发布消息的主题
            message: 消息内容

        Returns:
            接收到消息的订阅者数量；处于管道或事务环境时可能为 `0` / `-1`
            （具体语义以后端实现为准）。

        English
        --------
        Publish a message to the given topic.

        Returns:
            The number of subscribers that received the message. May be
            `0` / `-1` in a pipelined or transactional context (the exact
            semantics depend on the backend).
        """
        ...


__all__ = ["NotificationFunction"]
