"""Sentinel metrics 子包(M1.4)。

中文
----
``metrics/`` 集中 re-export SlidingWindow / MetricRegistry /
MetricSnapshot / MetricSink。ResourceRegistry 在 ``engine/`` 子包
(与 SlotChain / Engine 同侧),因为它属于 Engine 内部资源管理而非
指标收集。

English
--------
``metrics/`` re-exports SlidingWindow / MetricRegistry /
MetricSnapshot / MetricSink. ``ResourceRegistry`` lives in
``engine/`` (alongside SlotChain / Engine) because it is part of the
Engine's resource management, not metric collection."""

from __future__ import annotations

from .registry import MetricRegistry, ResourceCardinalityExceededEvent
from .sink import MetricSink, NoopMetricSink
from .sliding_window import SlidingWindow
from .snapshot import (
    ALLOWED_LABEL_KEYS,
    MetricLabelKey,
    MetricSnapshot,
    make_label,
)

__all__ = [
    "SlidingWindow",
    "MetricRegistry",
    "MetricSnapshot",
    "MetricLabelKey",
    "ALLOWED_LABEL_KEYS",
    "make_label",
    "MetricSink",
    "NoopMetricSink",
    "ResourceCardinalityExceededEvent",
]
