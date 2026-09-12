"""Sentinel Metric Sink(M1.4)。

中文
----
``MetricSink`` 是 MetricRegistry 的事件出口;**默认 Noop**(不消费
不抛错)。Engine 在 entry 完成时调用 ``MetricSink.emit(snapshot)``;
Dashboard / Prometheus exporter / OpenTelemetry bridge 可以实现
``MetricSink`` 把 snapshot 转成对应的导出格式。

设计要点:

- **Protocol + 不可变 Snapshot**:实现只读,不能反过来改 Registry
- **emit 永远不抛**:如果 sink 抛错,Engine 捕获并 swallow 到
  ``last_error``(与 Slot.on_entry_complete 行为一致)
- **Noop 默认**:M1.4 不引入 Prometheus / OTel 依赖,主包零
  3rd-party 必备

English
--------
Sentinel Metric Sink (M1.4).

``MetricSink`` is MetricRegistry's event export target; defaults to
``Noop`` (no consumption, no error). The Engine calls
``MetricSink.emit(snapshot)`` on entry completion; Dashboard /
Prometheus exporter / OpenTelemetry bridge can implement
``MetricSink`` to translate snapshots into the matching export
format.

Design points:

- **Protocol + immutable Snapshot** — read-only; cannot mutate the
  Registry from a sink.
- **emit never raises** — if a sink raises, the Engine catches and
  swallows to ``last_error`` (matches Slot.on_entry_complete
  behavior).
- **Noop by default** — M1.4 doesn't pull Prometheus / OTel; main
  wheel zero third-party."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .snapshot import MetricSnapshot


@runtime_checkable
class MetricSink(Protocol):
    """中文
    ----
    指标出口协议。

    实现要求:

    - ``emit(snapshot)`` 同步,接收不可变 snapshot,**不**抛异常
    - 实现可以是异步(M1.4 不强制;Engine 同步调用,慢 sink 会阻塞
      event loop);M1.5 优化路径上再考虑异步

    English
    --------
    Metric sink protocol.

    Implementation requirements:

    - ``emit(snapshot)`` synchronous, receives immutable snapshot,
      **must not** raise.
    - May be async (M1.4 not enforced; Engine calls synchronously, so
      a slow sink blocks the event loop); M1.5 may revisit for async
      path.
    """

    def emit(self, snapshot: MetricSnapshot) -> None:
        ...


class NoopMetricSink:
    """中文
    ----
    默认 noop sink。MetricRegistry 默认挂这个,什么也不做。

    English
    --------
    Default noop sink. MetricRegistry mounts this by default; does
    nothing.
    """

    __slots__ = ()

    def emit(self, snapshot: MetricSnapshot) -> None:  # noqa: ARG002
        """中文
        ----
        什么也不做。``snapshot`` 仅签名要求,不读。

        English
        --------
        No-op. ``snapshot`` is required by signature only.
        """
        return None


__all__ = ["MetricSink", "NoopMetricSink"]
