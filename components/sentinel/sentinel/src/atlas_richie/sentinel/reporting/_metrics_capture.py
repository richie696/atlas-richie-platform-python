"""Local adapter boundary between Sentinel metric producers and reporting."""

from __future__ import annotations

import inspect
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol, cast, runtime_checkable

from ..metrics.sink import MetricSink
from ..metrics.snapshot import LatencyHistogram, MetricSnapshot
from ..ports.system_metric_sampler import (
    SystemMetricLifecycle,
    SystemMetricSampler,
    SystemSnapshot,
)


class MetricCaptureSource(StrEnum):
    """Identify the Sentinel producer represented by a local capture."""

    ENTRY = "sentinel_entry"
    SYSTEM = "process_system"
    HTTP = "http_response"


@dataclass(frozen=True, slots=True)
class HttpMetricSnapshot:
    """Cumulative HTTP response snapshot retained for local reporting."""

    completed_requests: int
    latency_histogram: LatencyHistogram
    as_of_ns: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.completed_requests, bool)
            or not isinstance(self.completed_requests, int)
            or self.completed_requests < 0
        ):
            raise ValueError("completed_requests must be a non-negative integer")
        if not isinstance(self.latency_histogram, LatencyHistogram):
            raise TypeError("latency_histogram must be a LatencyHistogram")
        if self.latency_histogram.sample_count != self.completed_requests:
            raise ValueError("request count must match histogram sample count")
        if isinstance(self.as_of_ns, bool) or not isinstance(self.as_of_ns, int):
            raise TypeError("as_of_ns must be an integer")
        if self.as_of_ns < 0:
            raise ValueError("as_of_ns must be non-negative")


class HttpMetricProducerSnapshot(Protocol):
    """Structural input accepted from an optional HTTP framework adapter."""

    completed_requests: int
    latency_histogram: LatencyHistogram
    as_of_ns: int


@runtime_checkable
class HttpMetricProducer(Protocol):
    """Minimal producer shape needed to capture cumulative HTTP metrics."""

    def record_completed_request(self, *, duration_ns: int) -> None: ...

    def snapshot(self) -> HttpMetricProducerSnapshot: ...


@dataclass(frozen=True, slots=True)
class MetricCapture:
    """Typed in-process capture; it is not a wire envelope or protocol DTO."""

    source: MetricCaptureSource
    snapshot: MetricSnapshot | SystemSnapshot | HttpMetricSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.source, MetricCaptureSource):
            raise TypeError("source must use MetricCaptureSource")
        expected_type = {
            MetricCaptureSource.ENTRY: MetricSnapshot,
            MetricCaptureSource.SYSTEM: SystemSnapshot,
            MetricCaptureSource.HTTP: HttpMetricSnapshot,
        }[self.source]
        if not isinstance(self.snapshot, expected_type):
            raise TypeError(
                f"{self.source.value} capture requires {expected_type.__name__}"
            )

    @property
    def coalescing_key(self) -> tuple[object, ...]:
        """Return stable in-process identity without capture-time dimensions."""
        if self.source is MetricCaptureSource.ENTRY:
            return self.source, *sorted(self.snapshot.labels.items())
        return (self.source,)


@runtime_checkable
class MetricsReportingPort(Protocol):
    """Bounded local submission boundary owned by metrics reporting.

    Implementations must not wait for capacity or perform network/disk I/O.
    A brief wait for an in-memory mutex is permitted; callers must not rely
    on wait-free behavior or a hard latency bound.
    """

    def try_enqueue(self, capture: MetricCapture) -> bool:
        """Accept/coalesce, reject at capacity, or raise MetricsReportingError.

        Implementations may briefly wait for an in-memory mutex while
        updating bounded state, but must not wait for capacity or perform I/O.
        """
        ...


class MetricsReportingError(RuntimeError):
    """A reporting port failed before it could accept a local capture."""


class MetricsReportingBuffer(MetricsReportingPort):
    """Bounded process-local latest-snapshot buffer for reporting adapters."""

    __slots__ = (
        "_capacity",
        "_captures",
        "_coalesced_count",
        "_dropped_new_series_count",
        "_lock",
    )

    def __init__(self, *, capacity: int) -> None:
        """Create a buffer that can retain a positive number of identities."""
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self._capacity = capacity
        self._captures: OrderedDict[tuple[object, ...], MetricCapture] = OrderedDict()
        self._lock = Lock()
        self._coalesced_count = 0
        self._dropped_new_series_count = 0

    @property
    def capacity(self) -> int:
        """Return the fixed maximum number of pending capture identities."""
        return self._capacity

    @property
    def pending_count(self) -> int:
        """Return the number of currently buffered capture identities."""
        with self._lock:
            return len(self._captures)

    @property
    def coalesced_count(self) -> int:
        """Return the number of updates that replaced pending captures."""
        with self._lock:
            return self._coalesced_count

    @property
    def dropped_new_series_count(self) -> int:
        """Return the number of new identities rejected at capacity."""
        with self._lock:
            return self._dropped_new_series_count

    def try_enqueue(self, capture: MetricCapture) -> bool:
        """Add/coalesce locally; mutex contention may briefly delay this call.

        A full buffer rejects new identities immediately without waiting for
        capacity or performing I/O.
        """
        if not isinstance(capture, MetricCapture):
            raise TypeError("capture must be a MetricCapture")
        key = capture.coalescing_key
        with self._lock:
            if key in self._captures:
                self._captures[key] = capture
                self._captures.move_to_end(key)
                self._coalesced_count += 1
                return True
            if len(self._captures) >= self._capacity:
                self._dropped_new_series_count += 1
                return False
            self._captures[key] = capture
            return True

    def drain(self, *, limit: int | None = None) -> tuple[MetricCapture, ...]:
        """Remove oldest pending identities first, up to an optional limit."""
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit must be a positive integer or None")
        with self._lock:
            count = (
                len(self._captures)
                if limit is None
                else min(limit, len(self._captures))
            )
            return tuple(self._captures.popitem(last=False)[1] for _ in range(count))


class _EntryMetricSinkAdapter(MetricSink):
    """Translate registry snapshots into the separate metrics reporting port."""

    __slots__ = ("_enqueue",)

    def __init__(
        self,
        enqueue: Callable[[MetricCapture], None],
    ) -> None:
        self._enqueue = enqueue

    def emit(self, snapshot: MetricSnapshot) -> None:
        """Enqueue an immutable cumulative entry snapshot; never perform I/O."""
        self._enqueue(MetricCapture(MetricCaptureSource.ENTRY, snapshot))


class _SystemMetricSamplerAdapter(SystemMetricSampler):
    """Preserve sampler results while forwarding process samples to the port."""

    __slots__ = ("_enqueue", "_sampler")

    def __init__(
        self,
        sampler: SystemMetricSampler,
        enqueue: Callable[[MetricCapture], None],
    ) -> None:
        self._sampler = sampler
        self._enqueue = enqueue

    def sample(self) -> SystemSnapshot | Awaitable[SystemSnapshot]:
        """Forward sync or async samples without changing their values."""
        sample = self._sampler.sample()
        if inspect.isawaitable(sample):
            return self._record_async(sample)
        self._record(sample)
        return sample

    async def _record_async(self, sample: Awaitable[SystemSnapshot]) -> SystemSnapshot:
        snapshot = await sample
        self._record(snapshot)
        return snapshot

    def _record(self, snapshot: SystemSnapshot) -> None:
        self._enqueue(MetricCapture(MetricCaptureSource.SYSTEM, snapshot))


class _SystemMetricSamplerLifecycleAdapter(
    _SystemMetricSamplerAdapter, SystemMetricLifecycle
):
    """Forward optional entry accounting while capturing sampled values."""

    __slots__ = ("_sampler_lifecycle",)

    def __init__(
        self,
        sampler: SystemMetricSampler,
        enqueue: Callable[[MetricCapture], None],
    ) -> None:
        super().__init__(sampler, enqueue)
        self._sampler_lifecycle = cast(SystemMetricLifecycle, sampler)

    def record_enter(self) -> None:
        self._sampler_lifecycle.record_enter()

    def record_complete(self, *, success: bool) -> None:
        self._sampler_lifecycle.record_complete(success=success)


class _HttpMetricProducerAdapter:
    """Forward completed HTTP responses and enqueue cumulative snapshots."""

    __slots__ = ("_enqueue", "_producer", "_record_failure")

    def __init__(
        self,
        producer: HttpMetricProducer,
        enqueue: Callable[[MetricCapture], None],
        record_failure: Callable[[Exception], None],
    ) -> None:
        self._producer = producer
        self._enqueue = enqueue
        self._record_failure = record_failure

    def record_completed_request(self, *, duration_ns: int) -> None:
        """Preserve the producer update and isolate local capture failures."""
        try:
            self._producer.record_completed_request(duration_ns=duration_ns)
            snapshot = self._producer.snapshot()
            captured = HttpMetricSnapshot(
                completed_requests=snapshot.completed_requests,
                latency_histogram=snapshot.latency_histogram,
                as_of_ns=snapshot.as_of_ns,
            )
            self._enqueue(MetricCapture(MetricCaptureSource.HTTP, captured))
        except Exception as error:  # noqa: BLE001 - telemetry must not affect response
            self._record_failure(error)

    def snapshot(self) -> HttpMetricProducerSnapshot:
        """Preserve direct snapshot access for the middleware owner."""
        return self._producer.snapshot()


class MetricsCaptureAdapter:
    """Adapt Sentinel's entry, system, and HTTP metrics to one local port."""

    __slots__ = (
        "_counter_lock",
        "_enqueue_failure_count",
        "_last_enqueue_error_type",
        "_metric_sink",
        "_port",
        "_rejected_capture_count",
    )

    def __init__(self, port: MetricsReportingPort) -> None:
        """Bind producer adapters to the independently owned local port."""
        if not isinstance(port, MetricsReportingPort):
            raise TypeError("port must implement MetricsReportingPort")
        self._port = port
        self._counter_lock = Lock()
        self._enqueue_failure_count = 0
        self._rejected_capture_count = 0
        self._last_enqueue_error_type: str | None = None
        self._metric_sink = _EntryMetricSinkAdapter(self._enqueue)

    @property
    def enqueue_failure_count(self) -> int:
        """Return captures rejected by reporting-port or snapshot failures."""
        with self._counter_lock:
            return self._enqueue_failure_count

    @property
    def rejected_capture_count(self) -> int:
        """Return captures refused by the port without raising an error."""
        with self._counter_lock:
            return self._rejected_capture_count

    @property
    def last_enqueue_error_type(self) -> str | None:
        """Return only the latest exception class, never its potentially sensitive text."""
        with self._counter_lock:
            return self._last_enqueue_error_type

    def _record_enqueue_failure(self, error: Exception) -> None:
        with self._counter_lock:
            self._enqueue_failure_count += 1
            self._last_enqueue_error_type = type(error).__name__

    def _enqueue(self, capture: MetricCapture) -> None:
        """Centralize port result validation and bounded-capture diagnostics."""
        try:
            accepted = self._port.try_enqueue(capture)
            if type(accepted) is not bool:
                raise MetricsReportingError(
                    "metrics reporting port returned an invalid acceptance result"
                )
            if not accepted:
                with self._counter_lock:
                    self._rejected_capture_count += 1
        except Exception as error:  # noqa: BLE001 - telemetry must not affect admission
            # Reporting is observational: failure must not alter the completed
            # entry outcome, sampled value, or completed HTTP response.
            # Keep the failure visible by class name without propagating a
            # broken optional reporting implementation into Sentinel runtime.
            self._record_enqueue_failure(error)

    @property
    def metric_sink(self) -> MetricSink:
        """Return the MetricRegistry-compatible entry snapshot adapter."""
        return self._metric_sink

    def wrap_system_sampler(self, sampler: SystemMetricSampler) -> SystemMetricSampler:
        """Return a sampler adapter that also submits each sampled snapshot."""
        if not isinstance(sampler, SystemMetricSampler):
            raise TypeError("sampler must implement SystemMetricSampler")
        if isinstance(sampler, SystemMetricLifecycle):
            return _SystemMetricSamplerLifecycleAdapter(sampler, self._enqueue)
        return _SystemMetricSamplerAdapter(sampler, self._enqueue)

    def wrap_http_metrics(self, producer: HttpMetricProducer) -> HttpMetricProducer:
        """Capture completed HTTP responses through the same bounded local port.

        The producer is accepted structurally to keep the Sentinel core free of
        dependencies on ASGI or any other framework package. Its cumulative
        snapshot is copied into a core-owned internal DTO before enqueueing.
        """
        if not isinstance(producer, HttpMetricProducer):
            raise TypeError("producer must implement the HTTP metrics contract")
        return _HttpMetricProducerAdapter(
            producer,
            self._enqueue,
            self._record_enqueue_failure,
        )
