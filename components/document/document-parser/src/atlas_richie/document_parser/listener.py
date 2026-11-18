"""解析事件监听器与扇出。

对位 Java `cn.richie696.component.parser.ParseListener`。监听器是可选旁路：
解析产出的事件流仍是主通道，监听器用于观测/审计/进度上报。

一个监听器抛异常不得中断解析，也不得影响其它监听器 —— 与 Java 一致。
"""

from __future__ import annotations

import logging
from typing import Protocol, Sequence, runtime_checkable

from .model import (
    DocumentSegment,
    DocumentSummary,
    Failed,
    Finished,
    ImageSegment,
    ImageStreaming,
    ParseEvent,
    Streaming,
)

_log = logging.getLogger(__name__)


@runtime_checkable
class ParseListener(Protocol):
    def on_streaming(self, segment: DocumentSegment, source_name: str) -> None: ...

    def on_image(self, image: ImageSegment, source_name: str) -> None: ...

    def on_finished(self, summary: DocumentSummary, source_name: str) -> None: ...

    def on_error(self, error: Exception, source_name: str) -> None: ...


def dispatch_event(listener: ParseListener | None, event: ParseEvent) -> None:
    """Route one event to the matching callback; a raising listener is logged."""
    if listener is None:
        return
    try:
        if isinstance(event, Streaming):
            listener.on_streaming(event.segment, event.source_name)
        elif isinstance(event, ImageStreaming):
            listener.on_image(event.image, event.source_name)
        elif isinstance(event, Finished):
            listener.on_finished(event.summary, event.source_name)
        elif isinstance(event, Failed):
            listener.on_error(event.error, event.source_name)
    except Exception:  # noqa: BLE001 — 观测旁路不得影响解析主通道
        _log.exception("parse listener failed; event=%s", type(event).__name__)


class ListenerBus:
    """Fan out to several listeners, isolating each one's failures."""

    def __init__(self, listeners: Sequence[ParseListener] = ()) -> None:
        self._listeners = tuple(listeners)

    def __bool__(self) -> bool:
        return bool(self._listeners)

    def dispatch(self, event: ParseEvent) -> None:
        for listener in self._listeners:
            dispatch_event(listener, event)


__all__ = ["ParseListener", "ListenerBus", "dispatch_event"]