"""``RedisNotificationManager`` 的 Pub/Sub 订阅句柄。
----
镜像 Java 中 ``redis.manage.RedisNotificationManager`` 订阅者侧的生命周期：
一个长生命周期的 ``NotificationListener``，在专用守护线程上泵取 Redis
Pub/Sub 消息并分发给一组处理器（Observer 模式）。

线程模型：每个 listener 拥有：

- 一个 ``redis-py`` 的 ``PubSub`` 对象（自带连接），
- 一个守护线程，循环调用 ``pubsub.get_message(...)``，
- 一个用于协作关闭的 ``threading.Event``，
- 一个保护处理器列表的 ``threading.RLock``。

本模块是 ``cache_core.contracts.notification_listener.NotificationListener``
的 Redis 端实现。

English
--------
Pub/Sub subscription handle for `RedisNotificationManager`.

Mirrors the lifecycle of Java's `redis.manage.RedisNotificationManager`
subscriber side: a long-lived `NotificationListener` that pumps Redis
Pub/Sub messages on a dedicated daemon thread and dispatches them to a
list of handlers (Observer pattern).

Threading: each listener owns:
  - one redis-py's `PubSub` object (which holds its own connection),
  - one daemon thread that calls `pubsub.get_message(...)` in a loop,
  - one `threading.Event` for cooperative shutdown,
  - one `threading.RLock` protecting the handler list.

This module is the Redis-side implementation of
`cache_core.contracts.notification_listener.NotificationListener`.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

from atlas_richie.cache_core.contracts.notification_listener import (
    NotificationListener,
)

from ..serialization import decode_value


_log = logging.getLogger(__name__)


class RedisNotificationListener(NotificationListener):
    """由 ``RedisNotificationManager.subscribe()`` 返回的订阅句柄。
    ----
    镜像 Java ``MessageSubscriber`` 抽象类：长生命周期的 Pub/Sub 订阅者。

    生命周期::

        listener = mgr.subscribe("ch", handler)
        try:
            # ... listener 异步投递消息 ...
            ...
        finally:
            listener.close()  # 幂等

    处理器在 listener 拥有的守护线程上调用。处理器抛出异常会被记录，
    但不会停止消息泵取。

    English
    --------
    A subscription handle returned by `RedisNotificationManager.subscribe()`.

    Lifecycle:
        listener = mgr.subscribe("ch", handler)
        try:
            # ... listener delivers messages asynchronously ...
            ...
        finally:
            listener.close()  # idempotent

    Handlers are called on a daemon thread owned by this listener.
    Handlers that raise will be logged but will not stop the pump.
    """

    def __init__(
        self,
        pubsub: Any,
        topic: str,
        handlers: list[Callable[[str, Any], None]],
    ) -> None:
        self._pubsub = pubsub
        self._topic = topic
        self._handlers = handlers
        self._lock = threading.RLock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._pump,
            name=f"redis-pubsub:{topic}",
            daemon=True,
        )
        self._thread.start()

    # ── public lifecycle ───────────────────────────────────────────

    def is_open(self) -> bool:
        return not self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._pubsub.unsubscribe()
        except Exception:
            pass
        try:
            self._pubsub.close()
        except Exception:
            pass
        # Daemon thread will exit on its own once get_message returns None
        # after the connection is closed; no need to join().

    # ── internal ──────────────────────────────────────────────────

    def _pump(self) -> None:
        """Drain messages from redis-py's `PubSub` and dispatch to handlers.

        `pubsub.get_message(timeout=...)` returns:
          - `None` on timeout (we loop),
          - `{"type": "subscribe", ...}` confirmation (we skip),
          - `{"type": "message", "channel": ..., "data": ...}` real message.
        """
        while True:
            if self._closed:
                return
            try:
                msg = self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
            except Exception as exc:  # connection died
                if not self._closed:
                    _log.warning(
                        "redis pubsub pump error: %s; closing listener",
                        exc,
                    )
                return
            if msg is None:
                continue
            channel = msg.get("channel")
            data = msg.get("data")
            decoded = self._decode(data)
            with self._lock:
                handlers = list(self._handlers)
            for handler in handlers:
                try:
                    handler(channel, decoded)
                except Exception:
                    _log.exception(
                        "redis pubsub handler raised for channel=%s; "
                        "continuing",
                        channel,
                    )

    @staticmethod
    def _decode(data: Any) -> Any:
        """Decode redis-py payload. If it's `bytes` from a `decode_responses=False`
        client, decode utf-8 and try to parse JSON. Otherwise pass through."""
        if isinstance(data, (bytes, bytearray)):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return bytes(data)
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return text
        if isinstance(data, str):
            try:
                return json.loads(data)
            except (TypeError, ValueError):
                return data
        return decode_value(data)


__all__ = ["RedisNotificationListener"]
