"""Leader-gated periodic stream trimming.

对位 Java `cn.richie696.component.redis.streammq.stream.RedisStreamCleanup`。

Publishing trims only on XADD, so a stream that stops receiving messages keeps
its backlog forever. This job caps it on a schedule. Java takes a service-level
distributed lock so only one instance cleans up; here that is a `LeaderLease`
from coordination-core, which also auto-renews — a cleanup run longer than the
lease TTL must not lose leadership mid-job.

Scheduling comes from scheduling-core rather than a hand-rolled loop, so stop
is prompt and a crashing tick cannot kill the job.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Mapping

from atlas_richie.coordination_core import LeaderElector, LeaderLease
from atlas_richie.scheduling_core import Scheduler

from .bus import RedisStreamBus

_log = logging.getLogger(__name__)


def default_holder_id() -> str:
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True, slots=True)
class CleanupReport:
    skipped: bool = False
    trimmed: Mapping[str, int] = field(default_factory=dict)

    @property
    def total_removed(self) -> int:
        return sum(self.trimmed.values())


class StreamCleanup:
    """Periodically XTRIM a set of streams, on the leader only."""

    def __init__(
        self,
        bus: RedisStreamBus,
        limits: Mapping[str, int | None],
        *,
        elector: LeaderElector,
        default_max_len: int | None = None,
        resource: str = "stream-cleanup",
        holder_id: str | None = None,
        lease_ttl_seconds: float = 30.0,
        interval_seconds: float = 60.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self._bus = bus
        self._limits = dict(limits)
        self._default_max_len = default_max_len
        self._interval = interval_seconds
        self._lease = LeaderLease(
            elector,
            resource,
            holder_id or default_holder_id(),
            ttl_seconds=lease_ttl_seconds,
        )
        self._scheduler: Scheduler | None = None

    @property
    def is_leader(self) -> bool:
        return self._lease.is_leader

    def cleanup_once(self) -> CleanupReport:
        if not self._lease.is_leader:
            return CleanupReport(skipped=True)
        trimmed: dict[str, int] = {}
        for stream, override in self._limits.items():
            limit = override if override is not None else self._default_max_len
            if limit is None or limit <= 0:
                continue
            try:
                removed = self._bus.trim(stream, limit)
            except Exception:  # noqa: BLE001 — one bad stream must not stop the rest
                _log.exception("stream cleanup failed; stream=%s", stream)
                continue
            if removed:
                trimmed[stream] = removed
        return CleanupReport(trimmed=trimmed)

    def start(self) -> None:
        """Acquire leadership (best effort) and start the periodic job."""
        if self._scheduler is not None:
            return
        self._lease.start()
        scheduler = Scheduler(name="stream-cleanup")
        scheduler.schedule_fixed_delay(
            self._interval, self.cleanup_once, name="trim"
        )
        scheduler.start()
        self._scheduler = scheduler

    def stop(self, timeout: float | None = 5.0) -> None:
        scheduler = self._scheduler
        self._scheduler = None
        if scheduler is not None:
            scheduler.stop(timeout)
        self._lease.stop(timeout)

    def __enter__(self) -> StreamCleanup:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["CleanupReport", "StreamCleanup", "default_holder_id"]