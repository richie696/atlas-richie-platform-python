"""Bounded, non-blocking reporting of applied managed rule snapshots."""

from __future__ import annotations

import asyncio
import logging
import math
import weakref
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from atlas_richie.sentinel.rules import RuleRepository, RuleSnapshotAppliedEvent

from .errors import RuleReceiptDeliveryCode, RuleReceiptDeliveryError
from .producer import RulePublicationReceiptProducer

_LOGGER = logging.getLogger(__name__)
_MAX_PENDING_RECEIPTS = 4096


class RulePublicationReceiptTransport(Protocol):
    """Send exact receipt bytes and complete only after durable Collector ACK."""

    async def send(self, payload: bytes) -> None: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RulePublicationReceiptReporterConfig:
    """Finite queue, retry, and shutdown budgets for one runtime reporter."""

    max_pending: int = 256
    max_attempts: int = 5
    retry_base_seconds: float = 0.25
    retry_max_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if (
            type(self.max_pending) is not int
            or not 1 <= self.max_pending <= _MAX_PENDING_RECEIPTS
        ):
            raise ValueError(
                f"max_pending must be between 1 and {_MAX_PENDING_RECEIPTS}"
            )
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise ValueError("max_attempts must be between 1 and 100")
        delays = (self.retry_base_seconds, self.retry_max_seconds)
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in delays
        ):
            raise ValueError("retry delays must be finite numbers")
        if (
            self.retry_base_seconds <= 0
            or self.retry_max_seconds < self.retry_base_seconds
        ):
            raise ValueError("retry delay bounds are invalid")
        if (
            type(self.shutdown_timeout_seconds) not in (int, float)
            or not math.isfinite(self.shutdown_timeout_seconds)
            or self.shutdown_timeout_seconds <= 0
        ):
            raise ValueError("shutdown_timeout_seconds must be finite and positive")


@dataclass(frozen=True, slots=True)
class RulePublicationReceiptReporterStats:
    """Process-local counters; pending receipts are not durable storage."""

    accepted: int
    delivered: int
    queue_full: int
    invalid_event: int
    delivery_failed: int
    abandoned_on_close: int
    retries: int
    pending: int


class RulePublicationReceiptReporter:
    """Queue and deliver receipts without waiting on I/O in Repository callbacks.

    The queue is intentionally in memory. A short lock protects callback
    admission and counters; network calls, retries, and sleeps run on the
    reporter's async worker. Queue-full and shutdown losses are counted.
    """

    __slots__ = (
        "__weakref__",
        "_accepting",
        "_config",
        "_event_loop",
        "_idle_event",
        "_lock",
        "_pending",
        "_producer",
        "_sleep",
        "_started",
        "_stats",
        "_transport",
        "_wake_event",
        "_worker",
    )

    def __init__(
        self,
        producer: RulePublicationReceiptProducer,
        transport: RulePublicationReceiptTransport,
        config: RulePublicationReceiptReporterConfig | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not isinstance(producer, RulePublicationReceiptProducer):
            raise TypeError("producer must be RulePublicationReceiptProducer")
        if not isinstance(config, RulePublicationReceiptReporterConfig | None):
            raise TypeError(
                "config must be RulePublicationReceiptReporterConfig or None"
            )
        if not callable(getattr(transport, "send", None)) or not callable(
            getattr(transport, "aclose", None)
        ):
            raise TypeError("transport must provide async send and aclose methods")
        if not callable(sleep):
            raise TypeError("sleep must be callable")
        self._producer = producer
        self._transport = transport
        self._config = config or RulePublicationReceiptReporterConfig()
        self._sleep = sleep
        self._lock = Lock()
        self._pending: deque[bytes] = deque()
        self._stats = {
            "accepted": 0,
            "delivered": 0,
            "queue_full": 0,
            "invalid_event": 0,
            "delivery_failed": 0,
            "abandoned_on_close": 0,
            "retries": 0,
        }
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._idle_event: asyncio.Event | None = None
        self._worker: asyncio.Task[None] | None = None
        self._started = False
        self._accepting = False

    @property
    def stats(self) -> RulePublicationReceiptReporterStats:
        """Return an immutable, process-local delivery-counter snapshot."""
        with self._lock:
            values = dict(self._stats)
            pending = len(self._pending)
        return RulePublicationReceiptReporterStats(**values, pending=pending)

    async def start(self, repository: RuleRepository) -> None:
        """Subscribe to successful applications and start the single sender."""
        if not isinstance(repository, RuleRepository):
            raise TypeError("repository must be RuleRepository")
        if self._started:
            raise RuntimeError("receipt reporter has already been started")
        self._event_loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._accepting = True
        self._started = True
        self._worker = asyncio.create_task(
            self._run(), name="sentinel-rule-publication-receipt-reporter"
        )
        reporter_ref = weakref.ref(self)

        def receive(event: RuleSnapshotAppliedEvent) -> None:
            reporter = reporter_ref()
            if reporter is not None:
                reporter._on_snapshot_applied(event)

        repository.subscribe(receive)

    def _on_snapshot_applied(self, event: RuleSnapshotAppliedEvent) -> None:
        """Admit an event batch using only bounded local work."""
        loop = self._event_loop
        wake_event = self._wake_event
        if loop is None or wake_event is None:
            return
        with self._lock:
            if not self._accepting:
                return
            try:
                payloads = self._producer.for_applied_event(event)
            except Exception:  # noqa: BLE001 - must not fail Repository apply
                self._stats["invalid_event"] += 1
                return
            if not payloads:
                return
            if len(self._pending) + len(payloads) > self._config.max_pending:
                self._stats["queue_full"] += len(payloads)
                return
            self._pending.extend(payloads)
            self._stats["accepted"] += len(payloads)
            assert self._idle_event is not None
            self._idle_event.clear()
        try:
            loop.call_soon_threadsafe(wake_event.set)
        except RuntimeError:
            with self._lock:
                abandoned = len(self._pending)
                self._pending.clear()
                self._stats["abandoned_on_close"] += abandoned
                assert self._idle_event is not None
                self._idle_event.set()

    async def drain(self, timeout_seconds: float | None = None) -> None:
        """Wait until the current in-memory queue is empty."""
        if not self._started or self._idle_event is None:
            raise RuntimeError("receipt reporter has not been started")
        timeout = (
            self._config.shutdown_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        await asyncio.wait_for(self._idle_event.wait(), timeout=timeout)

    async def aclose(self) -> None:
        """Stop admission, drain for a bounded period, and account for losses."""
        with self._lock:
            self._accepting = False
        if not self._started:
            await self._close_transport()
            self._started = True
            return
        worker = self._worker
        wake_event = self._wake_event
        if worker is not None and wake_event is not None:
            wake_event.set()
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker),
                    timeout=self._config.shutdown_timeout_seconds,
                )
            except TimeoutError:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
            finally:
                self._worker = None
        with self._lock:
            abandoned = len(self._pending)
            self._pending.clear()
            self._stats["abandoned_on_close"] += abandoned
            if self._idle_event is not None:
                self._idle_event.set()
        await self._close_transport()

    async def _run(self) -> None:
        assert self._wake_event is not None
        while True:
            await self._wake_event.wait()
            self._wake_event.clear()
            while True:
                with self._lock:
                    payload = self._pending[0] if self._pending else None
                    if payload is None:
                        if not self._accepting:
                            return
                        assert self._idle_event is not None
                        self._idle_event.set()
                        break
                delivered = await self._deliver(payload)
                with self._lock:
                    if self._pending and self._pending[0] == payload:
                        self._pending.popleft()
                        self._stats[
                            "delivered" if delivered else "delivery_failed"
                        ] += 1
                    if not self._pending:
                        assert self._idle_event is not None
                        self._idle_event.set()

    async def _deliver(self, payload: bytes) -> bool:
        for attempt in range(self._config.max_attempts):
            try:
                await self._transport.send(payload)
                return True
            except asyncio.CancelledError:
                raise
            except RuleReceiptDeliveryError as error:
                if not error.retryable:
                    _LOGGER.warning(
                        "rule receipt delivery failed: %s", error.code.value
                    )
                    return False
                code = error.code
            except Exception:  # noqa: BLE001 - transport details may contain secrets
                code = RuleReceiptDeliveryCode.TRANSPORT_UNAVAILABLE
            if attempt + 1 >= self._config.max_attempts:
                _LOGGER.warning(
                    "rule receipt delivery exhausted retries: %s", code.value
                )
                return False
            with self._lock:
                self._stats["retries"] += 1
            delay = min(
                self._config.retry_base_seconds * (2**attempt),
                self._config.retry_max_seconds,
            )
            try:
                await self._sleep(delay)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - sleep adapter detail is untrusted
                _LOGGER.warning(
                    "rule receipt retry scheduling failed: transport_unavailable"
                )
                return False
        return False

    async def _close_transport(self) -> None:
        try:
            await self._transport.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - do not leak transport details
            _LOGGER.warning(
                "rule receipt transport close failed: transport_unavailable"
            )


__all__ = [
    "RulePublicationReceiptReporter",
    "RulePublicationReceiptReporterConfig",
    "RulePublicationReceiptReporterStats",
    "RulePublicationReceiptTransport",
]
