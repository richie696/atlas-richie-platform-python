"""Redis 通知管理器 + `NotificationFunction` (M3.A + R-221)。

中文
----
发布通知管理器，封装了 Redis 发布订阅（Pub/Sub）机制的通知功能。

**与 Stream 消息队列的区别：**

- **发布订阅（convertAndSend）**：基于 Redis 的 Pub/Sub 机制，消息只在内存中，
  只有在线订阅者能收到，离线后消息丢失，无持久化、无消费确认，
  适合事件通知、在线推送等场景。
- **Stream 消息队列**：基于 Redis Stream 数据结构，消息持久化存储，
  支持消费组、消息确认、消息堆积和回溯，适合可靠消息、异步任务、日志收集等场景。

本类只封装了发布订阅（Pub/Sub）机制，适用于在线通知、推送、事件广播等
对可靠性要求不高的场景。

English
--------
Redis-backed `NotificationOps` + `NotificationFunction` (M3.A + R-221).

Mirrors `cn.richie696.component.cache.redis.manage.RedisNotificationManager`
1:1. Implements both the low-level `NotificationOps` Protocol
(`publish` + `subscribe`) and the high-level `NotificationFunction`
Protocol (`publish_notify`).

Pub/Sub semantics (per the Java doc): fire-and-forget, no
persistence, no ack. Suitable for online event broadcast / push.
For reliable queueing with ack + replay, use a dedicated Stream-MQ
module instead.

Threading:
  - `publish` / `publish_notify` is a single `PUBLISH` command, no
    thread needed.
  - `subscribe` returns a `RedisNotificationListener` that owns its
    own daemon thread + redis-py `PubSub` connection.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from atlas_richie.cache_core.contracts.notification_listener import (
    NotificationListener,
)
from atlas_richie.cache_core.function.notification_function import (
    NotificationFunction,
)
from atlas_richie.cache_core.ops.notification_ops import NotificationOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache
from ..serialization import encode_value
from .redis_notification_listener import RedisNotificationListener


class RedisNotificationManager(NotificationOps, NotificationFunction):
    """中文
    ----
    Redis Pub/Sub 发布订阅管理器（火即弃语义）。

    English
    --------
    Redis-backed Pub/Sub publisher + subscriber (fire-and-forget).
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        # Redis 模板（JSON 序列化）
        self._backend = backend
        self._infra = infra

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    def _encode(self, message: Any) -> str | bytes:
        if isinstance(message, (bytes, bytearray)):
            return bytes(message)
        if isinstance(message, str):
            return message
        # JSON-encode complex values (matches Java's
        # `JsonUtils.serialize`).
        try:
            return json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return encode_value(message)

    def publish(self, topic: str, message: Any) -> int:
        """中文
        ----
        `PUBLISH` 到（已加命名空间前缀的）频道。

        返回接收到消息的订阅者数量。在 pipeline / transaction 内部
        始终返回 0（参见 Redis 文档）。

        English
        --------
        `PUBLISH` to the (already-namespaced) topic.

        Returns the number of subscribers that received the message.
        Returns 0 inside a pipeline / transaction (per the Redis
        docs).
        """
        return int(
            self._backend.raw_client().publish(
                self._k(topic), self._encode(message)
            )
        )

    def publish_notify(self, topic: str, message: Any) -> int:
        """中文
        ----
        `NotificationFunction` 接口下 `publish` 的别名（与 Java
        `NotificationFunction.publishNotify` 1:1 对齐）。

        English
        --------
        `NotificationFunction` alias for `publish`.
        """
        return self.publish(topic, message)

    def subscribe(
        self,
        topic: str,
        handler: Callable[[str, Any], None],
    ) -> NotificationListener:
        """中文
        ----
        在（已加命名空间前缀的）频道上打开订阅。

        返回的 `RedisNotificationListener` 在专属守护线程上派发消息；
        caller 用完需调用 `close()` 释放。

        English
        --------
        Open a subscription on a (namespaced) topic.

        The returned `RedisNotificationListener` pumps messages on a
        dedicated daemon thread; the caller is responsible for calling
        `close()` when done.
        """
        pubsub = self._backend.raw_client().pubsub()
        pubsub.subscribe(self._k(topic))
        return RedisNotificationListener(
            pubsub=pubsub,
            topic=self._k(topic),
            handlers=[handler],
        )


__all__ = ["RedisNotificationManager"]
