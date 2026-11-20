"""`4.5 事件总线（对位 Java `HookBus` / `DefaultHookBus`）。

同步发布 + 异常隔离 + 多订阅者 fan-out。按**事件的精确类型**分发（不做父类
匹配），与 Java 的 `event.getClass()` 查找一致。
"""

from __future__ import annotations

import threading
from typing import Protocol, TypeVar, runtime_checkable

from .events import HookEvent

EventT = TypeVar("EventT", bound=HookEvent)


@runtime_checkable
class HookSubscriber(Protocol):
    """`4.5.11 事件订阅者。"""

    def on_event(self, event: EventT) -> None:
        """`4.5.12 接收事件；实现应保证不抛异常（HookBus 会隔离，但会记警告）。"""
        ...


@runtime_checkable
class Subscription(Protocol):
    """`4.5.13 订阅反注册 token。"""

    def close(self) -> None:
        """`4.5.14 取消订阅；幂等。"""
        ...


@runtime_checkable
class HookBus(Protocol):
    """`4.5.15 事件总线。

    实现需保证：
    - 多订阅者 fan-out（按注册顺序）
    - 一个订阅者抛异常不影响其他订阅者
    - 无订阅者的事件静默丢弃
    """

    def subscribe(self, event_type: type[EventT], subscriber: HookSubscriber[EventT]) -> Subscription:
        """`4.5.16 注册订阅者，返回反注册 token。"""
        ...

    def publish(self, event: HookEvent) -> None:
        """`4.5.17 派发事件；订阅者异常被隔离。"""
        ...

    def diagnostic_view(self) -> list[str]:
        """`4.5.18 各事件类型的订阅者数（`4.5.19 形式），用于诊断 / 测试。"""
        ...


class _Subscription:
    """`4.5.20 订阅 token；`close()` 幂等。"""

    def __init__(self, bus: "DefaultHookBus", event_type: type[HookEvent], subscriber: object) -> None:
        self._bus = bus
        self._event_type = event_type
        self._subscriber = subscriber
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._unsubscribe(self._event_type, self._subscriber)

    def __enter__(self) -> "_Subscription":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class DefaultHookBus:
    """`4.5.21 默认事件总线实现。

    `4.5.22 同步发布（与调用方同线程）——简单且可预测；订阅者要异步化请自行
    `4.5.23（Java 侧同此建议：Micrometer 注册等）。
    `4.5.24 线程安全：订阅者列表用写时复制（读无锁），类型映射由锁保护。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[type[HookEvent], tuple[object, ...]] = {}

    def subscribe(self, event_type: type[EventT], subscriber: HookSubscriber[EventT]) -> Subscription:
        if event_type is None:
            raise ValueError("event_type must not be None")
        if subscriber is None:
            raise ValueError("subscriber must not be None")
        with self._lock:
            current = self._subscribers.get(event_type, ())
            self._subscribers[event_type] = current + (subscriber,)
        return _Subscription(self, event_type, subscriber)

    def publish(self, event: HookEvent) -> None:
        if event is None:
            return
        with self._lock:
            subscribers = self._subscribers.get(type(event), ())
        for subscriber in subscribers:
            try:
                subscriber.on_event(event)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — 订阅者异常必须被隔离
                continue

    def diagnostic_view(self) -> list[str]:
        with self._lock:
            items = self._subscribers.items()
        return sorted(f"{event_type.__name__}→{len(subscribers)}" for event_type, subscribers in items)

    def subscriber_count(self, event_type: type[HookEvent]) -> int:
        """`4.5.25 某事件类型的订阅者数量（诊断 / 测试用）。"""
        with self._lock:
            return len(self._subscribers.get(event_type, ()))

    def _unsubscribe(self, event_type: type[HookEvent], subscriber: object) -> None:
        with self._lock:
            current = self._subscribers.get(event_type, ())
            if subscriber not in current:
                return
            remaining = tuple(item for item in current if item is not subscriber)
            if remaining:
                self._subscribers[event_type] = remaining
            else:
                self._subscribers.pop(event_type, None)


__all__ = ["DefaultHookBus", "HookBus", "HookSubscriber", "Subscription"]
