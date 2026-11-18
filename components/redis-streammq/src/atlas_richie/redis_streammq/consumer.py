"""Consumer loop: idempotent processing, retry accounting and retry-to-DLQ.

Retry exhaustion is decided from Redis' own pending delivery count, so it survives
process restarts and is shared across consumers of the same group.

Deviation from Java: `ConsumerConfig.error_strategy` defaults to `DEAD_LETTER`
here (Java defaults to `SKIP`) because retry-to-DLQ is the behaviour this port is
asked to provide. `SKIP` is still available and acks exhausted messages away.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from atlas_richie.scheduling_core import Scheduler

from .bus import RedisStreamBus
from .idempotency import IdempotencyGuard
from .model import ConsumerConfig, ErrorStrategy, EventContext, StreamMessage

_log = logging.getLogger(__name__)


@dataclass
class ConsumerStats:
    """Cumulative counters across polls (对位 Java getConsumerStats)."""

    polls: int = 0
    processed: int = 0
    skipped_duplicate: int = 0
    dead_lettered: int = 0
    awaiting_retry: int = 0
    skipped_error: int = 0
    poll_errors: int = 0

    def absorb(self, outcome: PollOutcome) -> None:
        self.polls += 1
        self.processed += outcome.processed
        self.skipped_duplicate += outcome.skipped_duplicate
        self.dead_lettered += outcome.dead_lettered
        self.awaiting_retry += outcome.awaiting_retry
        self.skipped_error += outcome.skipped_error


@dataclass(frozen=True, slots=True)
class PollOutcome:
    processed: int = 0
    skipped_duplicate: int = 0
    dead_lettered: int = 0
    awaiting_retry: int = 0
    skipped_error: int = 0


class StreamConsumer:
    def __init__(
        self,
        bus: RedisStreamBus,
        config: ConsumerConfig,
        handler: Callable[[StreamMessage], None],
        *,
        guard: IdempotencyGuard | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._handler = handler
        self._guard = guard if guard is not None else IdempotencyGuard(bus.client)
        self._stats = ConsumerStats()
        self._stats_lock = threading.Lock()
        self._scheduler: Scheduler | None = None

    def poll_once(self) -> PollOutcome:
        config = self._config
        pending = self._bus.read(
            config.stream_key, config.group, config.consumer, count=config.count, last_id="0"
        )
        fresh = self._bus.read(
            config.stream_key,
            config.group,
            config.consumer,
            count=config.count,
            block_millis=config.block_millis,
            last_id=">",
        )
        # Read counts AFTER the reads: re-delivering a pending entry increments
        # its Redis delivery counter, so a pre-read snapshot would lag by one.
        counts = self._bus.delivery_counts(config.stream_key, config.group, config.consumer)
        seen: set[str] = set()
        outcome = {"processed": 0, "skipped_duplicate": 0, "dead_lettered": 0,
                   "awaiting_retry": 0, "skipped_error": 0}
        for message in [*pending, *fresh]:
            if message.id in seen:
                continue
            seen.add(message.id)
            self._handle_one(message, counts.get(message.id, 1), outcome)
        result = PollOutcome(**outcome)
        with self._stats_lock:
            self._stats.absorb(result)
        return result

    def _handle_one(self, message: StreamMessage, deliveries: int, outcome: dict[str, int]) -> None:
        config = self._config
        context = EventContext(config.stream_key, config.group, message.id)

        if config.idempotency_enabled:
            key = message.business_id or message.id
            if not self._guard.try_acquire(key):
                self._bus.ack(config.stream_key, config.group, message.id)
                outcome["skipped_duplicate"] += 1
                return
        else:
            key = None

        try:
            self._handler(message)
        except Exception as error:  # noqa: BLE001 — handler is caller code
            if config.error_strategy is ErrorStrategy.RETRY:
                # Java：立即进程内重试一次；成功则正常确认，失败留待下次投递。
                try:
                    self._handler(message)
                except Exception:  # noqa: BLE001
                    if key is not None:
                        self._guard.release(key)
                    outcome["awaiting_retry"] += 1
                    return
                outcome["processed"] += 1
                if config.auto_ack:
                    self._bus.ack(config.stream_key, config.group, message.id)
                return
            if config.error_strategy is ErrorStrategy.NO_ACK:
                # 不确认、不进 DLQ，留待后续处理（对位 Java NO_ACK）。
                if key is not None:
                    self._guard.release(key)
                outcome["awaiting_retry"] += 1
                return
            if deliveries >= config.max_retries:
                if config.error_strategy is ErrorStrategy.DEAD_LETTER:
                    self._bus.send_to_dead_letter(
                        message,
                        error,
                        context,
                        config.consumer,
                        strategy=config.dead_letter_strategy,
                        retry_count=deliveries,
                    )
                    outcome["dead_lettered"] += 1
                else:
                    _log.error(
                        "message dropped after retries; stream=%s id=%s errorType=%s",
                        config.stream_key, message.id, type(error).__name__,
                    )
                    outcome["skipped_error"] += 1
                self._bus.ack(config.stream_key, config.group, message.id)
            else:
                # Leave it pending so the next poll re-delivers it, and give back
                # the idempotency claim so the retry is not mistaken for a duplicate.
                if key is not None:
                    self._guard.release(key)
                outcome["awaiting_retry"] += 1
            return

        outcome["processed"] += 1
        if config.auto_ack:
            self._bus.ack(config.stream_key, config.group, message.id)

    def run(self, max_polls: int) -> list[PollOutcome]:
        """Bounded loop; a production deployment supplies its own scheduler."""
        return [self.poll_once() for _ in range(max_polls)]

    # ── 常驻生命周期（经 scheduling-core）─────────────────────────

    @property
    def running(self) -> bool:
        return self._scheduler is not None

    @property
    def stats(self) -> ConsumerStats:
        with self._stats_lock:
            return ConsumerStats(**vars(self._stats))

    def start(self, *, poll_interval_seconds: float = 1.0) -> None:
        """Run as a daemon: fixed-delay poll loop with prompt graceful stop."""
        if self._scheduler is not None:
            return
        scheduler = Scheduler(name=f"stream-consumer:{self._config.group}")
        scheduler.schedule_fixed_delay(
            poll_interval_seconds, self._poll_safely, name="poll"
        )
        scheduler.start()
        self._scheduler = scheduler

    def stop(self, timeout: float | None = 5.0) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is not None:
            scheduler.stop(timeout)

    def _poll_safely(self) -> None:
        try:
            self.poll_once()
        except Exception:  # noqa: BLE001 — 一次轮询失败不得杀死常驻循环
            with self._stats_lock:
                self._stats.poll_errors += 1
            _log.exception(
                "consumer poll failed; stream=%s group=%s",
                self._config.stream_key, self._config.group,
            )

    def __enter__(self) -> StreamConsumer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["ConsumerStats", "PollOutcome", "StreamConsumer"]
