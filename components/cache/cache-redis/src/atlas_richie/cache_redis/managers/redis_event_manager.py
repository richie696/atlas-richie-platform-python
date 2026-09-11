"""Redis Key 事件订阅与通知管理器。
----
``EventOps`` + ``EventFunction`` 的 Redis 后端实现（M3.A + R-226）。

封装基于 Redis 发布/订阅机制的 Key 事件监听能力，支持对过期、删除等
事件的订阅与回调。

主要功能：

- 按模式订阅 Key 事件（如 ``__keyevent@0__:expired``）。
- 注册监听器并转发到业务回调。
- 用于缓存失效通知、分布式事件驱动等场景。

镜像 ``cn.richie696.component.cache.redis.manage.RedisEventManager`` 的结构。
同时实现底层 ``EventOps`` Protocol 与高层 ``EventFunction`` Protocol。

两种事件机制共存：

1. **Redis keyspace 事件**（``subscribe_key_event``）—— 服务端、跨进程。
   需要启用 ``notify-keyspace-events``。传输的数据是触发事件的 key 名称。

2. **进程内事件总线**（``fire`` / ``register_listener`` / ``on``）——
   R-226 新增。纯 Python；监听器在触发线程上同步调用。监听器可以是任何
   ``Callable[[Any], None]``。

服务器必须启用 ``notify-keyspace-events``（例如 ``KEA``）才能真正触发
keyspace 事件。进程内总线没有外部依赖。

线程模型：

- Keyspace：每次 ``subscribe_key_event`` 启动一个守护线程，从 ``redis-py``
  的 ``PubSub`` 对象中泵取消息。
- 进程内：``fire()`` 是同步的；监听器异常会被捕获并记录，但不会中断后续
  监听器。

English
--------
Redis-backed `EventOps` + `EventFunction` (M3.A + R-226).

Mirrors `cn.richie696.component.cache.redis.manage.RedisEventManager`
1:1. Implements both the low-level `EventOps` Protocol and the
high-level `EventFunction` Protocol.

Two event mechanisms coexist:

1. **Redis keyspace events** (`subscribe_key_event`) — server-side,
   cross-process. Requires `notify-keyspace-events` enabled. The
   data delivered is the key name that triggered the event.

2. **In-process event bus** (`fire` / `register_listener` / `on`) —
   R-226 addition. Pure Python; listeners are invoked synchronously
   on the firing thread. Listeners may be any `Callable[[Any], None]`.

Server must have `notify-keyspace-events` enabled (e.g. `KEA`) for
keyspace events to actually fire. The in-process bus has no
external dependencies.

Threading:
  - Keyspace: each `subscribe_key_event` call starts a daemon
    thread that pumps messages from the `redis-py` `PubSub` object.
  - In-process: `fire()` is synchronous; listener errors are
    caught and logged but do not stop subsequent listeners.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

from atlas_richie.cache_core.contracts.keyspace_listener import (
    KeyspaceEventListener,
)
from atlas_richie.cache_core.function.event_function import EventFunction
from atlas_richie.cache_core.ops.event_ops import EventOps

from ..redis_cache_infrastructure import RedisCacheInfrastructure
from ..redis_distributed_cache import RedisDistributedCache


_log = logging.getLogger(__name__)


# Type alias for in-process event listeners.
EventListener = Callable[[Any], None]


class RedisEventManager(EventOps, EventFunction):
    """Redis Key 事件订阅与通知管理器。
    ----
    Redis 后端的 keyspace 事件订阅 + 进程内事件总线。

    keyspace 一侧处理跨进程事件（key 过期、删除等）。进程内总线用于单个
    Python 进程中的应用层 pub-sub。

    English
    --------
    Redis-backed keyspace event subscription + in-process event bus.

    The keyspace side is for cross-process events (key-expired,
    key-deleted, etc.). The in-process bus is for application-level
    pub-sub within a single Python process.
    """

    def __init__(
        self,
        backend: RedisDistributedCache,
        infra: RedisCacheInfrastructure,
    ) -> None:
        self._backend = backend
        self._infra = infra
        self._subscriptions: Dict[str, _Subscription] = {}
        self._lock = threading.Lock()
        # R-226: in-process event bus.
        self._listeners: Dict[str, List[EventListener]] = {}
        self._listener_lock = threading.RLock()

    def _k(self, key: str) -> str:
        return self._backend.make_key(key)

    # ── EventOps + EventFunction (M3.A): keyspace events ────────

    def subscribe_key_event(
        self, pattern: str, listener: KeyspaceEventListener
    ) -> None:
        # Redis keyspace event channels are special (e.g.
        # `__keyevent@0__:expired`) and are NOT namespaced — they're
        # server-wide. We pass the pattern as-is to `psubscribe`.
        # The listener receives the FULL key name (namespaced) as
        # `data`, so the caller can filter by their own namespace
        # prefix if they want.
        client = self._backend.raw_client()
        pubsub = client.pubsub()
        sub = _Subscription(pubsub, listener, pattern, pattern)
        sub.start()
        with self._lock:
            self._subscriptions[pattern] = sub

    # ── R-226: in-process event bus ─────────────────────────────

    def register_listener(
        self, event_name: str, listener: EventListener
    ) -> None:
        """Register a listener for an in-process event.

        Multiple listeners per event are allowed; they fire in
        registration order. A listener that raises will be logged
        but will not stop subsequent listeners from firing.
        """
        with self._listener_lock:
            self._listeners.setdefault(event_name, []).append(listener)

    def on(
        self, event_name: str, listener: EventListener
    ) -> None:
        """Alias for `register_listener` to match the legacy `cache.on()` API."""
        self.register_listener(event_name, listener)

    def unregister_listener(
        self, event_name: str, listener: EventListener
    ) -> bool:
        """Remove a previously-registered listener. Returns True if
        the listener was found and removed."""
        with self._listener_lock:
            listeners = self._listeners.get(event_name)
            if not listeners:
                return False
            try:
                listeners.remove(listener)
                return True
            except ValueError:
                return False

    def fire(self, event_name: str, payload: Any = None) -> int:
        """Fire an in-process event synchronously.

        All registered listeners are invoked in registration order.
        Returns the number of listeners that were called.
        """
        with self._listener_lock:
            listeners = list(self._listeners.get(event_name, []))
        for listener in listeners:
            try:
                listener(payload)
            except Exception:
                _log.exception(
                    "event listener for %r raised; continuing",
                    event_name,
                )
        return len(listeners)

    def listener_count(self, event_name: str) -> int:
        with self._listener_lock:
            return len(self._listeners.get(event_name, []))

    # ── lifecycle ──────────────────────────────────────────────

    def close(self) -> None:
        """Stop all keyspace pump threads and close pubsub
        connections. In-process listeners are NOT touched (they
        stay registered; the bus is just dormant in this process)."""
        with self._lock:
            subs = list(self._subscriptions.values())
            self._subscriptions.clear()
        for sub in subs:
            sub.stop()


class _Subscription:
    """A single pattern subscription with its pump thread."""

    def __init__(
        self,
        pubsub: Any,
        listener: KeyspaceEventListener,
        user_pattern: str,
        namespaced_pattern: str,
    ) -> None:
        self._pubsub = pubsub
        self._listener = listener
        self._user_pattern = user_pattern
        self._namespaced_pattern = namespaced_pattern
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._pubsub.psubscribe(self._namespaced_pattern)
        self._thread = threading.Thread(
            target=self._pump,
            name=f"redis-event-pump:{self._user_pattern}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._pubsub.close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _pump(self) -> None:
        try:
            while not self._stop_event.is_set():
                msg = self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if msg is None:
                    continue
                # `msg` shape: {'type': 'pmessage', 'pattern': b'...',
                # 'channel': b'...', 'data': b'...'}
                pattern = msg.get("pattern", b"")
                channel = msg.get("channel", b"")
                data = msg.get("data", b"")
                if isinstance(pattern, bytes):
                    pattern = pattern.decode("utf-8", errors="replace")
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8", errors="replace")
                try:
                    self._listener.on_message(
                        str(pattern), str(channel), data
                    )
                except Exception:
                    # Swallow listener errors so a buggy handler does
                    # not kill the pump thread.
                    pass
        except Exception:
            # Connection lost — silently exit; caller can re-subscribe.
            pass


__all__ = ["RedisEventManager"]
