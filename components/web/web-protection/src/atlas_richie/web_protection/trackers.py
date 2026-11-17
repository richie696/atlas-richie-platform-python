"""Stateful protection trackers: nonce replay and login brute force.

Ported from `NonceCache` and `LoginAttemptTracker` (Java), both framework-free.

Both are per-process. A multi-instance deployment needs a shared store to make
replay and lockout decisions globally; inject one at the adapter layer rather
than adding a Redis dependency here.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class NonceCache:
    """TTL nonce store; `put_if_absent` is the atomic check-and-record primitive."""

    def __init__(self, ttl_seconds: float, *, clock=time.monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttlSeconds must be > 0")
        self._ttl = ttl_seconds
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def put_if_absent(self, nonce: str) -> bool:
        """True when the nonce is fresh (absent or expired), False on replay."""
        if nonce is None:
            raise ValueError("nonce must not be null")
        now = self._clock()
        with self._lock:
            previous = self._seen.get(nonce)
            if previous is None or now - previous > self._ttl:
                self._seen[nonce] = now
                return True
            return False

    def contains(self, nonce: str | None) -> bool:
        if nonce is None:
            return False
        now = self._clock()
        with self._lock:
            timestamp = self._seen.get(nonce)
            if timestamp is None:
                return False
            if now - timestamp > self._ttl:
                del self._seen[nonce]
                return False
            return True

    def size(self) -> int:
        now = self._clock()
        with self._lock:
            for nonce in [n for n, ts in self._seen.items() if now - ts > self._ttl]:
                del self._seen[nonce]
            return len(self._seen)


class LoginAttemptTracker:
    """Sliding-window failure counting with a lockout once the threshold is hit."""

    def __init__(
        self,
        window_seconds: float,
        max_attempts: int,
        lockout_seconds: float,
        *,
        clock=time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("windowSeconds must be > 0")
        if max_attempts <= 0:
            raise ValueError("maxAttempts must be > 0")
        if lockout_seconds <= 0:
            raise ValueError("lockoutSeconds must be > 0")
        self._window = window_seconds
        self._max_attempts = max_attempts
        self._lockout = lockout_seconds
        self._clock = clock
        self._entries: dict[str, tuple[deque[float], float]] = {}
        self._lock = threading.Lock()

    def is_locked(self, key: str | None) -> bool:
        if key is None:
            return False
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False
            attempts, locked_until = entry
            if locked_until > now:
                return True
            if not attempts:
                del self._entries[key]
            else:
                self._evict(attempts, now - self._window)
            return False

    def record_failure(self, key: str | None) -> int:
        """Record one failure and return the in-window attempt count."""
        if key is None:
            return 0
        now = self._clock()
        with self._lock:
            attempts, locked_until = self._entries.get(key, (deque(), 0.0))
            self._evict(attempts, now - self._window)
            attempts.append(now)
            if len(attempts) >= self._max_attempts:
                locked_until = now + self._lockout
            self._entries[key] = (attempts, locked_until)
            return len(attempts)

    def record_success(self, key: str | None) -> None:
        if key is None:
            return
        with self._lock:
            self._entries.pop(key, None)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    @staticmethod
    def _evict(attempts: deque[float], cutoff: float) -> None:
        while attempts and attempts[0] < cutoff:
            attempts.popleft()


__all__ = ["LoginAttemptTracker", "NonceCache"]
