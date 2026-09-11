"""Redis Key 事件订阅与通知 API 函数。
----
Redis Key 事件订阅与通知 API 管理器接口。
封装了基于 Redis 发布订阅机制的 Key 事件监听能力，支持对 Key 过期、
删除等事件的订阅与回调处理。适用于缓存失效通知、分布式事件驱动等场景。

English
--------
Redis Key-space event subscription function (high-level, built on `EventOps`).

Mirrors `cn.richie696.component.cache.function.EventFunction`. Java's
`org.springframework.data.redis.connection.MessageListener` is replaced
by the framework-level `KeyspaceEventListener` Protocol.

Server must have `notify-keyspace-events` enabled (e.g. `KEA`) for
`__keyevent@<db>__:expired` / `:del` to actually fire.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ..contracts.keyspace_listener import KeyspaceEventListener


class EventFunction(Protocol):
    """Redis Key 事件订阅与通知 API。

    封装了基于 Redis 发布订阅机制的 Key 事件监听能力，支持对 Key 过期、
    删除等事件的订阅与回调处理。适用于缓存失效通知、分布式事件驱动等场景。

    English
    --------
    Redis Key 事件订阅与通知 API。
    """

    @abstractmethod
    def subscribe_key_event(
        self, pattern: str, listener: KeyspaceEventListener
    ) -> None:
        """订阅指定模式的 Key 事件。

        Args:
            pattern: 事件模式（如 `__keyevent@0__:expired`）
            listener: 消息监听器，收到事件时回调

        English
        --------
        Subscribe to key events matching the given pattern.

        Args:
            pattern: 事件模式（如 `__keyevent@0__:expired`）
            listener: 消息监听器，收到事件时回调
        """
        ...


__all__ = ["EventFunction"]
