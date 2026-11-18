"""Leader election contracts and a per-process reference implementation.

Zero dependencies. A shared-store implementation (see
`atlas-richie-coordination-redis`) is required for real multi-instance election;
the in-memory one here is for single-process use and tests.

Fencing follows the same principle as sentinel-cluster's owner-epoch fencing: a
stale holder's renew or release must never affect the current holder. Every
acquisition issues a strictly increasing `fencing_token`, and operations are
matched against the exact (holder, token) pair that was granted.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Leadership:
    """A granted lease. `fencing_token` increases on every new acquisition."""

    resource: str
    holder_id: str
    fencing_token: int
    expires_at: float

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at

    @property
    def lease_value(self) -> str:
        """Identity used for compare-and-set operations by shared stores."""
        return f"{self.holder_id}:{self.fencing_token}"


class LeaderElector(Protocol):
    def try_acquire(self, resource: str, holder_id: str, ttl_seconds: float) -> Leadership | None:
        """Grant the lease when free; return None when someone else holds it."""
        ...

    def renew(self, lease: Leadership, ttl_seconds: float) -> Leadership | None:
        """Extend a lease we still hold; None means leadership was lost."""
        ...

    def release(self, lease: Leadership) -> bool:
        """Give up a lease we still hold. Never deletes another holder's lease."""
        ...

    def current(self, resource: str) -> Leadership | None:
        ...


class InMemoryLeaderElector:
    """Thread-safe per-process elector. Not shared across instances."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._leases: dict[str, Leadership] = {}
        self._tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    def try_acquire(self, resource: str, holder_id: str, ttl_seconds: float) -> Leadership | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        now = self._clock()
        with self._lock:
            held = self._leases.get(resource)
            if held is not None and not held.is_expired(now):
                return None
            token = self._tokens.get(resource, 0) + 1
            self._tokens[resource] = token
            lease = Leadership(resource, holder_id, token, now + ttl_seconds)
            self._leases[resource] = lease
            return lease

    def renew(self, lease: Leadership, ttl_seconds: float) -> Leadership | None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        now = self._clock()
        with self._lock:
            held = self._leases.get(lease.resource)
            if held is None or held.lease_value != lease.lease_value or held.is_expired(now):
                return None
            renewed = Leadership(lease.resource, lease.holder_id, lease.fencing_token, now + ttl_seconds)
            self._leases[lease.resource] = renewed
            return renewed

    def release(self, lease: Leadership) -> bool:
        with self._lock:
            held = self._leases.get(lease.resource)
            if held is None or held.lease_value != lease.lease_value:
                return False
            del self._leases[lease.resource]
            return True

    def current(self, resource: str) -> Leadership | None:
        now = self._clock()
        with self._lock:
            held = self._leases.get(resource)
            if held is None or held.is_expired(now):
                return None
            return held


class LeaderLease:
    """Holds a lease and keeps renewing it on a background thread.

    Java's `optimisticWithRenewal` auto-renews; a caller-driven `renew()` means a
    busy leader silently loses its lease mid-job. This watchdog renews at
    `ttl/3` by default and re-acquires after a loss, so leadership recovers
    without the caller polling.

    Loss is reported via `on_lost` and reflected in `is_leader`; work guarded by
    this lease must check `is_leader` (or the fencing token) before acting,
    because a renewal can fail between two ticks.
    """

    def __init__(
        self,
        elector: LeaderElector,
        resource: str,
        holder_id: str,
        *,
        ttl_seconds: float = 30.0,
        renew_interval_seconds: float | None = None,
        on_lost: Callable[[Leadership], None] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        interval = renew_interval_seconds if renew_interval_seconds is not None else ttl_seconds / 3
        if interval <= 0 or interval >= ttl_seconds:
            raise ValueError("renew_interval_seconds must be within (0, ttl_seconds)")
        self._elector = elector
        self._resource = resource
        self._holder_id = holder_id
        self._ttl = ttl_seconds
        self._interval = interval
        self._on_lost = on_lost
        self._lease: Leadership | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def resource(self) -> str:
        return self._resource

    @property
    def leadership(self) -> Leadership | None:
        with self._lock:
            return self._lease

    @property
    def is_leader(self) -> bool:
        with self._lock:
            return self._lease is not None

    def start(self) -> Leadership | None:
        """Acquire immediately (best effort) and start renewing. Idempotent."""
        with self._lock:
            if self._thread is not None:
                return self._lease
            self._stop.clear()
            self._lease = self._elector.try_acquire(
                self._resource, self._holder_id, self._ttl
            )
            thread = threading.Thread(
                target=self._run, name=f"leader-lease:{self._resource}", daemon=True
            )
            self._thread = thread
        thread.start()
        return self.leadership

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                lease = self._lease
            if lease is not None:
                renewed = self._elector.renew(lease, self._ttl)
                if renewed is not None:
                    with self._lock:
                        self._lease = renewed
                    continue
                self._lost(lease)
            acquired = self._elector.try_acquire(
                self._resource, self._holder_id, self._ttl
            )
            if acquired is not None:
                with self._lock:
                    self._lease = acquired

    def _lost(self, lease: Leadership) -> None:
        with self._lock:
            self._lease = None
        if self._on_lost is not None:
            try:
                self._on_lost(lease)
            except Exception:  # noqa: BLE001 — a broken callback must not stop renewal
                _log.exception("leader lease on_lost callback failed; resource=%s", self._resource)

    def stop(self, timeout: float | None = 5.0) -> None:
        """Stop renewing and release the lease. Idempotent."""
        with self._lock:
            thread = self._thread
            self._thread = None
            lease = self._lease
            self._lease = None
        self._stop.set()
        if thread is not None:
            thread.join(timeout)
        if lease is not None:
            try:
                self._elector.release(lease)
            except Exception:  # noqa: BLE001 — release is best effort on shutdown
                _log.exception("leader lease release failed; resource=%s", self._resource)

    def __enter__(self) -> LeaderLease:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["InMemoryLeaderElector", "LeaderElector", "LeaderLease", "Leadership"]
