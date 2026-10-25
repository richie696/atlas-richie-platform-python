"""Sentinel Metric Sink(M1.4)。

中文
----
``MetricSink`` 是 MetricRegistry 的事件出口;**默认 Noop**(不消费
不抛错)。每次成功记录 entry 结果后，MetricRegistry 同步调用
``MetricSink.emit(snapshot)``，传入对应 label 的累计快照；
Dashboard / Prometheus exporter / OpenTelemetry bridge 可以实现
``MetricSink`` 把 snapshot 转成对应的导出格式。

设计要点:

- **Protocol + 不可变 Snapshot**:实现只读,不能反过来改 Registry
- **emit 必须有界且本地**:Engine entry 完成路径同步调用它；实现只能
  做有界内存入队，不得等待容量、执行网络/数据库 IO；允许短暂等待
  有界内存状态更新所需的互斥锁，但不承诺 wait-free 或硬实时延迟
- **失败隔离**:sink 不应抛错；若仍抛错，Engine 捕获并记录到
  ``last_error``，不改变业务结果
- **Noop 默认**:M1.4 不引入 Prometheus / OTel 依赖,主包零
  3rd-party 必备

English
--------
Sentinel Metric Sink (M1.4).

``MetricSink`` is MetricRegistry's event export target; defaults to
``Noop`` (no consumption, no error). The Engine calls
``MetricSink.emit(snapshot)`` synchronously after each recorded entry,
with the cumulative snapshot for that label set; Dashboard /
Prometheus exporter / OpenTelemetry bridge can implement
``MetricSink`` to translate snapshots into the matching export
format.

Design points:

- **Protocol + immutable Snapshot** — read-only; cannot mutate the
  Registry from a sink.
- **emit is bounded and local** — the Engine calls it on the entry
  completion path, so implementations may only perform bounded in-memory
  enqueueing; they must reject at capacity instead of waiting for capacity,
  and must not perform network or database I/O. A brief wait for an
  in-memory mutex is permitted; this is not a wait-free or hard-realtime API.
- **Failure isolation** — a sink should not raise; if it does, the
  Engine records the exception in ``last_error`` without changing the
  business result.
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

    - ``emit(snapshot)`` 同步,接收不可变累计 snapshot
    - 只能做有界本地内存入队；满载时拒绝，不等待容量，也不执行网络/数据库 IO
    - 允许短暂等待内存状态更新所需的互斥锁；不承诺 wait-free 或硬实时延迟
    - 不得抛异常；Engine 会隔离意外异常并记录到 ``last_error``

    English
    --------
    Metric sink protocol.

    Implementation requirements:

    - ``emit(snapshot)`` synchronous, receives an immutable cumulative
      snapshot.
    - May only enqueue in bounded local memory; it must reject at
      capacity rather than wait for capacity and must not perform network
      or database I/O.
    - A brief wait for an in-memory mutex is permitted; this API does not
      promise wait-free behavior or a hard realtime latency bound.
    - Must not raise; the Engine isolates unexpected sink exceptions and
      records them in ``last_error``.
    """

    def emit(self, snapshot: MetricSnapshot) -> None: ...


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
