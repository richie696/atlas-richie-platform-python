"""Redis Key 空间事件订阅操作接口。

中文
----
Redis Key 空间事件订阅操作接口。
用于 L2 联动之外的自定义键事件监听（如过期、删除等），需服务端开启
`notify-keyspace-events`。

English
--------
Redis keyspace event subscription ops interface.

Mirrors `cn.richie696.component.cache.ops.EventOps`. Requires
server-side `notify-keyspace-events` to be enabled (e.g. `KEA`).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from ..contracts.keyspace_listener import KeyspaceEventListener


class EventOps(Protocol):
    """中文
    ----
    Redis Key 空间事件订阅操作接口。用于 L2 联动之外的自定义键事件监听
    （如过期、删除等），需服务端开启 `notify-keyspace-events`。

    English
    --------
    Redis keyspace event subscription ops. Used for L2 invalidation
    beyond the in-process flow. Server must have
    `notify-keyspace-events` enabled.
    """

    @abstractmethod
    def subscribe_key_event(self, pattern: str, listener: KeyspaceEventListener) -> None:
        """中文
        ----
        订阅指定模式的 Key 事件。

        Args:
            pattern: 事件模式（如 `__keyevent@0__:expired`）
            listener: 消息监听器

        English
        --------
        Subscribe to key events matching `pattern`.

        Args:
            pattern: Event pattern (e.g. `__keyevent@0__:expired`).
            listener: Message listener.
        """
        ...


__all__ = ["EventOps"]
