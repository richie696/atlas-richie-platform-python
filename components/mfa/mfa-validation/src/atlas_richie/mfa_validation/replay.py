"""Replay-prevention SPI and a per-process reference implementation.

The Java `ReplayAttackPreventionService` is bound to Servlet request context and
`GlobalCache` (Redis). Here the storage is an injected `ReplayGuard` Protocol, so
the core stays dependency-free: a single-process deployment can use the in-memory
guard below, while a multi-instance deployment plugs in a shared store (e.g. a
cache-redis backed adapter) without this package depending on Redis.

TTL semantics match Java: `time_window * replay_prevention_ttl_multiplier`, so a
code stays marked as used beyond its own validity window.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReplayPreventionProperties:
    time_window: int = 30
    replay_prevention_ttl_multiplier: int = 3

    @property
    def ttl_seconds(self) -> int:
        return self.time_window * self.replay_prevention_ttl_multiplier


class ReplayGuard(Protocol):
    """Tracks which (subject, time step) codes have already been consumed."""

    def is_code_used(self, user_id: str, tenant_id: str | int | None, time_step: int) -> bool: ...

    def mark_code_as_used(self, user_id: str, tenant_id: str | int | None, time_step: int) -> None: ...


def _key(user_id: str, tenant_id: str | int | None, time_step: int) -> str:
    return f"mfa:replay:{tenant_id if tenant_id is not None else '-'}:{user_id}:{time_step}"


class InMemoryReplayGuard:
    """Thread-safe per-process guard with lazy expiry.

    Not shared across processes: behind a load balancer each instance would keep
    its own markers, so a code could be replayed against a different instance.
    Use a shared-store implementation for multi-instance deployments.
    """

    def __init__(
        self,
        properties: ReplayPreventionProperties | None = None,
        *,
        clock=time.monotonic,
    ) -> None:
        self._properties = properties if properties is not None else ReplayPreventionProperties()
        self._clock = clock
        self._expires_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_code_used(self, user_id: str, tenant_id: str | int | None, time_step: int) -> bool:
        key = _key(user_id, tenant_id, time_step)
        with self._lock:
            self._purge()
            return key in self._expires_at

    def mark_code_as_used(self, user_id: str, tenant_id: str | int | None, time_step: int) -> None:
        key = _key(user_id, tenant_id, time_step)
        with self._lock:
            self._purge()
            self._expires_at[key] = self._clock() + self._properties.ttl_seconds

    def _purge(self) -> None:
        now = self._clock()
        for key in [key for key, expiry in self._expires_at.items() if expiry <= now]:
            del self._expires_at[key]


__all__ = [
    "InMemoryReplayGuard",
    "ReplayGuard",
    "ReplayPreventionProperties",
]
