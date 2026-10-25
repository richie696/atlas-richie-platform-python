"""Sentinel MetricRegistry(M1.4)。

中文
----
``MetricRegistry`` 维护每个 ``(label_tuple)`` 的计数(``admitted`` /
``blocked`` / ``succeeded`` / ``failed`` / ``cancelled`` / RT 总和),
提供按 label 过滤的 snapshot 查询。

设计要点:

- **低基数 label 强制**:registry 不接受 whitelist 外的 key(由
  ``snapshot.make_label`` 工厂保证;registry 本身再校验一次)
- **无 3rd-party 依赖**:纯 dict + counter
- **overflow 策略**:单 label 组合的 entry 数超过 ``max_samples`` 时
  停止累加(防 memory 爆炸),但仍保留最后一个 snapshot 可读
- **sink 解耦**:每次更新后同步调用 ``MetricSink.emit``;Sink 只能执行
  有界本地入队,不得执行网络/数据库 IO;M1.4 默认 ``NoopMetricSink``
- **线程模型**:Engine 在所属 asyncio event loop 的线程内写入注册表。
  ``record`` 与 ``iter_snapshots`` 不保证并发线程安全;返回的不可变
  ``MetricSnapshot`` 创建后可跨线程读取。

English
--------
Sentinel MetricRegistry (M1.4).

``MetricRegistry`` maintains per-``(label_tuple)`` counters
(``admitted`` / ``blocked`` / ``succeeded`` / ``failed`` /
``cancelled`` / RT total), and provides label-filtered snapshot
queries.

Design points:

- **Low-cardinality label enforcement** — registry refuses keys
  outside the whitelist (``snapshot.make_label`` factory guarantees
  it; registry re-validates as defense-in-depth).
- **No third-party deps** — plain dict + counter.
- **Overflow policy** — when entry count for one label combination
  exceeds ``max_samples``, accumulation stops (memory bound) but the
  last snapshot is still readable.
- **Sink decoupled** — ``MetricSink.emit`` is called synchronously after
  each update. A sink may only perform bounded local enqueueing; it must
  not perform network or database I/O. M1.4 defaults to
  ``NoopMetricSink``.
- **Thread model** — the Engine writes the registry on its owning
  ``asyncio`` event-loop thread. ``record`` and ``iter_snapshots`` are
  not safe to run concurrently from multiple threads. An immutable
  ``MetricSnapshot`` may be read across threads after it is created."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Mapping

from ..model.outcome import OutcomeKind
from ..model.resource import Resource
from .sink import MetricSink, NoopMetricSink
from .snapshot import (
    ALLOWED_LABEL_KEYS,
    DEFAULT_RT_HISTOGRAM_BOUNDS_NS,
    LatencyHistogram,
    MetricSnapshot,
    latency_histogram_bucket_index,
    make_label,
    validate_rt_histogram_bounds,
)


# 4 计数器 + 1 RT 总和(per label tuple)
@dataclass(slots=True)
class _Counter:
    event_count: int = 0
    admitted: int = 0
    blocked: int = 0
    succeeded: int = 0
    failed: int = 0
    cancelled: int = 0
    rt_total_ns: int = 0
    rt_count: int = 0
    rt_min_ns: int | None = None
    rt_max_ns: int | None = None
    rt_bucket_counts: list[int] = field(default_factory=list)

    def record(
        self,
        outcome: OutcomeKind,
        rt_ns: int,
        latency_bucket_bounds_ns: tuple[int, ...],
    ) -> None:
        """中文
        ----
        累加一个 entry;``rt_ns`` 仅在 SUCCEEDED / FAILED 时有意义。

        English
        ----
        Accumulate one entry; ``rt_ns`` is meaningful only for
        SUCCEEDED / FAILED.
        """
        self.event_count += 1
        if outcome is OutcomeKind.SUCCEEDED:
            self.admitted += 1
            self.succeeded += 1
            self._record_latency(rt_ns, latency_bucket_bounds_ns)
        elif outcome is OutcomeKind.FAILED:
            self.admitted += 1
            self.failed += 1
            self._record_latency(rt_ns, latency_bucket_bounds_ns)
        elif outcome is OutcomeKind.CANCELLED:
            self.admitted += 1
            self.cancelled += 1
        elif outcome is OutcomeKind.BLOCKED:
            self.blocked += 1
        elif outcome is OutcomeKind.ADMITTED:
            self.admitted += 1

    def _record_latency(
        self, rt_ns: int, latency_bucket_bounds_ns: tuple[int, ...]
    ) -> None:
        if not self.rt_bucket_counts:
            self.rt_bucket_counts = [0] * (len(latency_bucket_bounds_ns) + 1)
        self.rt_bucket_counts[
            latency_histogram_bucket_index(latency_bucket_bounds_ns, rt_ns)
        ] += 1
        self.rt_total_ns += rt_ns
        self.rt_count += 1
        self.rt_min_ns = rt_ns if self.rt_min_ns is None else min(self.rt_min_ns, rt_ns)
        self.rt_max_ns = rt_ns if self.rt_max_ns is None else max(self.rt_max_ns, rt_ns)


@dataclass(slots=True)
class ResourceCardinalityExceededEvent:
    """中文
    ----
    Resource 基数超限事件;Engine 触发事件订阅者(默认 Noop)。

    English
    --------
    Resource cardinality exceeded event; Engine fires this to event
    subscribers (default Noop).
    """

    current_count: int
    max_resources: int
    at_ns: int


class MetricRegistry:
    """中文
    ----
    指标注册表(M1.4)。

    用法::

        registry = MetricRegistry(sink=MySink())
        registry.record(
            resource=resource,
            outcome=OutcomeKind.SUCCEEDED,
            rt_ns=elapsed_ns,
        )
        for snap in registry.iter_snapshots():
            ...

    English
    --------
    Metric registry (M1.4).

    Usage::

        registry = MetricRegistry(sink=MySink())
        registry.record(
            resource=resource,
            outcome=OutcomeKind.SUCCEEDED,
            rt_ns=elapsed_ns,
        )
        for snap in registry.iter_snapshots():
            ...
    """

    __slots__ = (
        "_counters",
        "_latency_bucket_bounds_ns",
        "_noop_sink",
        "_overflow_fired",
        "max_samples",
        "sink",
    )

    def __init__(
        self,
        *,
        sink: MetricSink | None = None,
        max_samples: int = 1_000_000,
        latency_bucket_bounds_ns: tuple[int, ...] = DEFAULT_RT_HISTOGRAM_BOUNDS_NS,
    ) -> None:
        if max_samples <= 0:
            raise ValueError(f"max_samples must be positive (got {max_samples})")
        # Key = tuple of (key, value) sorted by key; immutable + hashable
        self._counters: dict[tuple[tuple[str, str], ...], _Counter] = {}
        self._noop_sink = NoopMetricSink()
        self.sink: MetricSink = sink if sink is not None else self._noop_sink
        self.max_samples = max_samples
        self._overflow_fired: bool = False
        self._latency_bucket_bounds_ns = validate_rt_histogram_bounds(
            latency_bucket_bounds_ns
        )

    @property
    def latency_bucket_bounds_ns(self) -> tuple[int, ...]:
        """Return the immutable histogram boundaries owned by this registry."""
        return self._latency_bucket_bounds_ns

    def _key(self, label: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
        # Whitelist check (defense-in-depth)
        for k in label:
            if k not in ALLOWED_LABEL_KEYS:
                raise ValueError(
                    f"metric label key {k!r} not in whitelist; "
                    f"use snapshot.make_label() factory"
                )
        return tuple(sorted(label.items()))

    def record(
        self,
        *,
        resource: Resource,
        outcome: OutcomeKind,
        rt_ns: int = 0,
        extra_label: Mapping[str, str] | None = None,
    ) -> None:
        """中文
        ----
        记录一个 entry outcome。

        ``extra_label`` 只能添加白名单内的 key;主要给 Metric / Rule
        事件附加 rule_kind / block_reason(由调用方从
        ``snapshot.make_label`` 构造)。

        English
        --------
        Record one entry outcome.

        ``extra_label`` can only add whitelisted keys; primarily for
        Metric / Rule events to attach rule_kind / block_reason
        (constructed by caller via ``snapshot.make_label``).
        When a non-noop sink is configured, it receives the updated
        cumulative snapshot synchronously; that sink must enqueue only in
        bounded local memory, reject at capacity, and avoid network/database
        I/O. A brief wait for an in-memory mutex is permitted; no wait-free
        or hard-realtime guarantee is made.
        """
        base = make_label(resource=resource)
        if isinstance(rt_ns, bool) or not isinstance(rt_ns, int) or rt_ns < 0:
            raise ValueError("rt_ns must be a non-negative integer")
        if extra_label:
            for k in extra_label:
                if k not in ALLOWED_LABEL_KEYS:
                    raise ValueError(f"extra_label key {k!r} not in whitelist")
            merged = {**base, **extra_label}
        else:
            merged = base
        key = self._key(merged)
        counter = self._counters.get(key)
        if counter is None:
            # New label combination — check overflow
            if len(self._counters) >= self.max_samples:
                self._fire_overflow()
                return
            counter = _Counter()
            self._counters[key] = counter
        # Also bound per-label accumulation (total samples for this key)
        if counter.event_count >= self.max_samples:
            return
        counter.record(outcome, rt_ns, self._latency_bucket_bounds_ns)
        if self.sink is not self._noop_sink:
            self.sink.emit(self._snapshot_for(key, counter, time.time_ns()))

    def _fire_overflow(self) -> None:
        if not self._overflow_fired:
            self._overflow_fired = True
            # M1.4 占位:Engine 未来会在初始化时挂 ResourceCardinalityExceeded
            # 事件订阅者,目前先记录到 sink 之外的 last_error 风格变量
            # (M1.5 加 event 订阅)
            # 这里只 print warning 到 stderr 不污染 stdout
            import sys

            print(
                f"MetricRegistry: resource cardinality exceeded "
                f"max_samples={self.max_samples}",
                file=sys.stderr,
            )

    def iter_snapshots(self) -> list[MetricSnapshot]:
        """中文
        ----
        返回当前所有 (label, counter) 的不可变 snapshot 列表。

        English
        --------
        Return immutable snapshot list of all (label, counter) pairs.
        """
        now = time.time_ns()
        return [
            self._snapshot_for(key, counter, now)
            for key, counter in self._counters.items()
        ]

    def _snapshot_for(
        self,
        key: tuple[tuple[str, str], ...],
        counter: _Counter,
        at_ns: int,
    ) -> MetricSnapshot:
        """Build one immutable cumulative snapshot for an updated label set."""
        histogram = LatencyHistogram(
            boundaries_ns=self._latency_bucket_bounds_ns,
            bucket_counts=tuple(counter.rt_bucket_counts)
            if counter.rt_bucket_counts
            else (0,) * (len(self._latency_bucket_bounds_ns) + 1),
            sample_count=counter.rt_count,
            total_ns=counter.rt_total_ns,
            min_ns=counter.rt_min_ns,
            max_ns=counter.rt_max_ns,
        )
        return MetricSnapshot(
            at_ns=at_ns,
            labels=dict(key),
            admitted=counter.admitted,
            blocked=counter.blocked,
            succeeded=counter.succeeded,
            failed=counter.failed,
            cancelled=counter.cancelled,
            avg_rt_ns=(
                counter.rt_total_ns // counter.rt_count if counter.rt_count > 0 else 0
            ),
            latency_histogram=histogram,
        )

    def emit_all(self) -> None:
        """中文
        ----
        强制 flush 全部 snapshot 到 sink(测试 / 关闭时用)。

        English
        --------
        Force-flush all snapshots to sink (used at test / shutdown).
        """
        for snap in self.iter_snapshots():
            try:
                self.sink.emit(snap)
            except BaseException:
                # Sink 必须不抛;但如果抛了,swallow
                pass

    def __len__(self) -> int:
        return len(self._counters)


__all__ = [
    "MetricRegistry",
    "ResourceCardinalityExceededEvent",
]
