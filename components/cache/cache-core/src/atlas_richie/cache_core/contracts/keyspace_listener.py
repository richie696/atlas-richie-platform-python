"""Redis Key 空间事件订阅接口。
----
Redis Key 空间事件订阅操作接口。
用于 L2 联动之外的自定义键事件监听（如过期、删除等），
需服务端开启 `notify-keyspace-events`。

English
--------
Keyspace event listener contract.

Mirrors `cn.richie696.component.cache.ops.EventOps`. Requires the
server to have `notify-keyspace-events` enabled (e.g. `KEA`).
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class KeyspaceEventListener(Protocol):
    """单条 Key 空间事件回调。

    English
    --------
    A single keyspace event callback.
    """

    def on_message(self, pattern: str, channel: str, data: bytes | str) -> None:
        ...


class KeyspaceEventBus(Protocol):
    """Redis Key 空间事件订阅操作接口。

    用于 L2 联动之外的自定义键事件监听（如过期、删除等），
    需服务端开启 `notify-keyspace-events`。

    English
    --------
    Mirrors `ops/EventOps.java`. Used for L2 invalidation beyond the
    in-process flow. Server must have `notify-keyspace-events` enabled.
    """

    @abstractmethod
    def subscribe(self, pattern: str, listener: KeyspaceEventListener) -> None:
        """订阅指定模式的 Key 事件。

        Args:
            pattern: 事件模式（如 `__keyevent@0__:expired`）
            listener: 消息监听器

        English
        --------
        Subscribe to key events matching the given pattern.

        Args:
            pattern: 事件模式（如 `__keyevent@0__:expired`）
            listener: 消息监听器
        """
        ...


__all__ = ["KeyspaceEventBus", "KeyspaceEventListener"]
