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

import threading
import time
from dataclasses import dataclass
from typing import Protocol


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


__all__ = ["InMemoryLeaderElector", "LeaderElector", "Leadership"]
