"""Bounded process-local metrics for completed ASGI HTTP responses."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from atlas_richie.sentinel.metrics import (
    DEFAULT_RT_HISTOGRAM_BOUNDS_NS,
    LatencyHistogram,
    latency_histogram_bucket_index,
    validate_rt_histogram_bounds,
)


@dataclass(frozen=True, slots=True)
class ASGIHttpMetricsSnapshot:
    """Immutable process-local count and latency histogram snapshot.

    Only completed HTTP responses are represented. No route, status, header,
    identity, request body, or response body data is retained.
    """

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


class ASGIHttpMetrics:
    """Collect a bounded histogram of completed responses for one process.

    The registry is an optional local producer for later aggregation. It does
    not send data, choose a transport, or expose request-derived labels.
    Updates are lock-protected because one ASGI app may be shared across
    execution threads; snapshots contain only immutable aggregate values.
    """

    __slots__ = (
        "_as_of_ns",
        "_bucket_counts",
        "_completed_requests",
        "_latency_bucket_bounds_ns",
        "_lock",
        "_max_ns",
        "_min_ns",
        "_total_ns",
    )

    def __init__(
        self,
        *,
        latency_bucket_bounds_ns: tuple[int, ...] = DEFAULT_RT_HISTOGRAM_BOUNDS_NS,
        as_of_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        self._latency_bucket_bounds_ns = validate_rt_histogram_bounds(
            latency_bucket_bounds_ns
        )
        self._as_of_ns = as_of_ns
        self._lock = Lock()
        self._completed_requests = 0
        self._bucket_counts = [0] * (len(self._latency_bucket_bounds_ns) + 1)
        self._total_ns = 0
        self._min_ns: int | None = None
        self._max_ns: int | None = None

    def record_completed_request(self, *, duration_ns: int) -> None:
        """Record one response only after its final ASGI body send succeeds."""
        bucket_index = latency_histogram_bucket_index(
            self._latency_bucket_bounds_ns, duration_ns
        )
        with self._lock:
            self._completed_requests += 1
            self._bucket_counts[bucket_index] += 1
            self._total_ns += duration_ns
            self._min_ns = (
                duration_ns if self._min_ns is None else min(self._min_ns, duration_ns)
            )
            self._max_ns = (
                duration_ns if self._max_ns is None else max(self._max_ns, duration_ns)
            )

    def snapshot(self) -> ASGIHttpMetricsSnapshot:
        """Return a consistent, immutable view without exposing raw samples."""
        with self._lock:
            completed_requests = self._completed_requests
            latency_histogram = LatencyHistogram(
                boundaries_ns=self._latency_bucket_bounds_ns,
                bucket_counts=tuple(self._bucket_counts),
                sample_count=completed_requests,
                total_ns=self._total_ns,
                min_ns=self._min_ns,
                max_ns=self._max_ns,
            )
        return ASGIHttpMetricsSnapshot(
            completed_requests=completed_requests,
            latency_histogram=latency_histogram,
            as_of_ns=self._as_of_ns(),
        )


__all__ = ["ASGIHttpMetrics", "ASGIHttpMetricsSnapshot"]
