"""Asynchronous durable-receipt Reporter over Sentinel's local capture Port."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from atlas_richie.contracts.reporting.v2 import (
    MAX_SAFE_INTEGER,
    METRICS_V2_CADENCE_SECONDS,
    METRICS_V2_MAX_ACTIVE_RESOURCES,
    MetricsReceipt,
    MetricsReceiptProtocolError,
    decode_metrics_receipt,
    encode_metrics_snapshot,
)
from atlas_richie.sentinel.reporting import (
    MetricCapture,
    MetricCaptureSource,
    MetricsReportingBuffer,
    MetricsReportingPort,
)

from .errors import MetricsReceiptMismatchError, MetricsTransportError
from .snapshot_builder import MetricsSnapshotBuilder

_SAFE_SEQUENCE_MAX = MAX_SAFE_INTEGER


@runtime_checkable
class MetricsV2Transport(Protocol):
    """Send one exact encoded snapshot and return the durable ACK body."""

    async def send(self, payload: bytes) -> bytes: ...


class ReporterClock(Protocol):
    """Clock boundary injectable for deterministic cadence and identity tests."""

    def utc_now(self) -> datetime: ...

    def monotonic_ns(self) -> int: ...


class _SystemReporterClock:
    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class ReporterFlushResult(StrEnum):
    """Outcome of one bounded Reporter send attempt."""

    NO_DATA = "no_data"
    ACKNOWLEDGED = "acknowledged"
    RETRY_PENDING = "retry_pending"
    DROPPED_AFTER_RETRIES = "dropped_after_retries"


@dataclass(frozen=True, slots=True)
class MetricsV2ReporterConfig:
    """Explicit identity, buffer, cadence, and finite retry settings."""

    reporter_id: str
    buffer_capacity: int = 1024
    max_attempts: int = 5
    retry_base_seconds: float = 0.25
    retry_max_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.reporter_id, str) or not self.reporter_id.strip():
            raise ValueError("reporter_id must be non-blank")
        if self.reporter_id != self.reporter_id.strip() or len(self.reporter_id) > 200:
            raise ValueError("reporter_id must be a bounded trimmed identifier")
        if (
            type(self.buffer_capacity) is not int
            or not 1 <= self.buffer_capacity <= 65_536
        ):
            raise ValueError("buffer_capacity must be between 1 and 65536")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        if (
            type(self.retry_base_seconds) not in (int, float)
            or type(self.retry_max_seconds) not in (int, float)
            or not math.isfinite(self.retry_base_seconds)
            or not math.isfinite(self.retry_max_seconds)
            or self.retry_base_seconds <= 0
            or self.retry_max_seconds < self.retry_base_seconds
        ):
            raise ValueError("retry delay bounds are invalid")


@dataclass(frozen=True, slots=True)
class _PendingSnapshot:
    """Exact bytes plus receipt identity retained across uncertain delivery."""

    payload: bytes
    reporter_id: str
    startup_epoch: UUID
    sequence: int
    digest: str


class MetricsV2Reporter:
    """Buffer captures, emit cumulative snapshots, and retire only durable ACKs.

    ``try_enqueue`` is deliberately synchronous, bounded, and local. The async
    loop owns mapping, transport, retry, receipt verification, and shutdown.
    Uncertain delivery retains identical bytes and identity until acknowledged
    or explicitly dropped after the configured finite attempt limit.
    """

    __slots__ = (
        "_buffer",
        "_builder",
        "_clock",
        "_config",
        "_dropped_after_retries",
        "_epoch",
        "_last_error_type",
        "_latest",
        "_loop_task",
        "_monotonic_origin_ns",
        "_next_sequence",
        "_pending",
        "_queue_rejected_count",
        "_rejected_resource_count",
        "_resource_lock",
        "_resource_names",
        "_retry_attempts",
        "_retry_count",
        "_sleep",
        "_transport",
    )

    def __init__(
        self,
        config: MetricsV2ReporterConfig,
        transport: MetricsV2Transport,
        *,
        clock: ReporterClock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        buffer: MetricsReportingPort | None = None,
        builder: MetricsSnapshotBuilder | None = None,
        startup_epoch: UUID | None = None,
    ) -> None:
        if not isinstance(config, MetricsV2ReporterConfig):
            raise TypeError("config must be MetricsV2ReporterConfig")
        if not isinstance(transport, MetricsV2Transport):
            raise TypeError("transport must implement MetricsV2Transport")
        if buffer is not None and not isinstance(buffer, MetricsReportingPort):
            raise TypeError("buffer must implement MetricsReportingPort")
        self._config = config
        self._transport = transport
        self._clock = clock or _SystemReporterClock()
        self._sleep = sleep
        self._buffer = (
            MetricsReportingBuffer(capacity=config.buffer_capacity)
            if buffer is None
            else buffer
        )
        self._builder = builder or MetricsSnapshotBuilder()
        self._epoch = startup_epoch or uuid4()
        if type(self._epoch) is not UUID:
            raise TypeError("startup_epoch must be UUID")
        self._monotonic_origin_ns = self._clock.monotonic_ns()
        self._next_sequence = 1
        self._latest: dict[tuple[object, ...], MetricCapture] = {}
        self._pending: deque[_PendingSnapshot] = deque()
        self._resource_lock = Lock()
        self._resource_names: set[str] = set()
        self._rejected_resource_count = 0
        self._retry_attempts = 0
        self._dropped_after_retries = 0
        self._retry_count = 0
        self._queue_rejected_count = 0
        self._last_error_type: str | None = None
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def startup_epoch(self) -> UUID:
        """Return this process reporter's immutable opaque startup epoch."""
        return self._epoch

    @property
    def next_sequence(self) -> int:
        """Return the next sequence not yet acknowledged or explicitly dropped."""
        return self._next_sequence

    @property
    def dropped_after_retries(self) -> int:
        """Return snapshots explicitly discarded after bounded retries."""
        return self._dropped_after_retries

    @property
    def rejected_resource_count(self) -> int:
        """Return local rejections at the frozen active resource limit."""
        with self._resource_lock:
            return self._rejected_resource_count

    @property
    def queue_rejected_count(self) -> int:
        """Return captures rejected by the bounded capture buffer."""
        with self._resource_lock:
            return self._queue_rejected_count

    @property
    def retry_count(self) -> int:
        """Return failed send/receipt attempts without retaining error messages."""
        return self._retry_count

    @property
    def last_error_type(self) -> str | None:
        """Return the last failure class only; raw transport details are omitted."""
        return self._last_error_type

    @property
    def pending_count(self) -> int:
        """Return captures buffered plus exact snapshot batches awaiting ACK."""
        return len(self._pending) + self._buffer.pending_count

    def try_enqueue(self, capture: MetricCapture) -> bool:
        """Accept/coalesce locally; never await, serialize, or call transport."""
        if not isinstance(capture, MetricCapture):
            raise TypeError("capture must be a MetricCapture")
        if capture.source is not MetricCaptureSource.ENTRY:
            accepted = self._buffer.try_enqueue(capture)
            if not accepted:
                with self._resource_lock:
                    self._queue_rejected_count += 1
            return accepted
        resource = capture.snapshot.labels.get("resource")
        if not resource:
            with self._resource_lock:
                self._rejected_resource_count += 1
            return False
        with self._resource_lock:
            if (
                resource not in self._resource_names
                and len(self._resource_names) >= METRICS_V2_MAX_ACTIVE_RESOURCES
            ):
                self._rejected_resource_count += 1
                return False
            accepted = self._buffer.try_enqueue(capture)
            if accepted:
                self._resource_names.add(resource)
            else:
                self._queue_rejected_count += 1
            return accepted

    def retry_delay_seconds(self) -> float:
        """Return finite capped exponential backoff for the pending body."""
        exponent = max(0, self._retry_attempts - 1)
        return min(
            self._config.retry_max_seconds,
            self._config.retry_base_seconds * (2**exponent),
        )

    async def flush_once(self) -> ReporterFlushResult:
        """Attempt one exact snapshot delivery without hiding uncertain ACKs."""
        self._refresh_latest()
        if not self._pending:
            if not self._latest:
                return ReporterFlushResult.NO_DATA
            if self._next_sequence > _SAFE_SEQUENCE_MAX:
                raise RuntimeError("Metrics V2 reporter sequence is exhausted")
            self._prepare_pending()
        current = self._pending[0]
        try:
            receipt = decode_metrics_receipt(
                await self._transport.send(current.payload)
            )
            self._validate_receipt(receipt, current)
        except asyncio.CancelledError:
            raise
        except (
            MetricsTransportError,
            MetricsReceiptProtocolError,
            MetricsReceiptMismatchError,
        ) as error:
            self._retry_attempts += 1
            self._retry_count += 1
            self._last_error_type = type(error).__name__
            if self._retry_attempts < self._config.max_attempts:
                return ReporterFlushResult.RETRY_PENDING
            self._pending.popleft()
            self._next_sequence = current.sequence + 1
            self._retry_attempts = 0
            self._dropped_after_retries += 1
            return ReporterFlushResult.DROPPED_AFTER_RETRIES

        self._pending.popleft()
        self._next_sequence = current.sequence + 1
        self._retry_attempts = 0
        return ReporterFlushResult.ACKNOWLEDGED

    async def start(self) -> None:
        """Start the single sequential cadence loop; repeated starts are safe."""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._run(), name="metrics-v2-reporter")

    async def aclose(self) -> None:
        """Stop the cadence loop and close an owned async transport if supported."""
        task = self._loop_task
        self._loop_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        close = getattr(self._transport, "aclose", None)
        if close is not None:
            await close()

    async def _run(self) -> None:
        while True:
            result = await self.flush_once()
            delay = (
                self.retry_delay_seconds()
                if result is ReporterFlushResult.RETRY_PENDING
                else METRICS_V2_CADENCE_SECONDS
            )
            await self._sleep(delay)

    def _refresh_latest(self) -> None:
        for capture in self._buffer.drain():
            self._latest[capture.coalescing_key] = capture

    def _prepare_pending(self) -> None:
        monotonic_now_ns = self._clock.monotonic_ns()
        elapsed_ns = monotonic_now_ns - self._monotonic_origin_ns
        if elapsed_ns < 0:
            raise RuntimeError("reporter monotonic clock regressed")
        batches = self._builder.build(
            self._latest.values(),
            reporter_id=self._config.reporter_id,
            startup_epoch=self._epoch,
            first_sequence=self._next_sequence,
            captured_at=self._clock.utc_now(),
            capture_elapsed_ns=elapsed_ns,
        )
        for batch in batches:
            payload = encode_metrics_snapshot(batch.snapshot)
            self._pending.append(
                _PendingSnapshot(
                    payload,
                    self._config.reporter_id,
                    self._epoch,
                    batch.snapshot.sequence,
                    hashlib.sha256(payload).hexdigest(),
                )
            )

    @staticmethod
    def _validate_receipt(receipt: MetricsReceipt, pending: _PendingSnapshot) -> None:
        if (
            receipt.reporter_id != pending.reporter_id
            or receipt.startup_epoch != pending.startup_epoch
            or receipt.sequence != pending.sequence
            or receipt.body_sha256 != pending.digest
        ):
            raise MetricsReceiptMismatchError()


__all__ = [
    "MetricsV2Reporter",
    "MetricsV2ReporterConfig",
    "MetricsV2Transport",
    "ReporterFlushResult",
]
