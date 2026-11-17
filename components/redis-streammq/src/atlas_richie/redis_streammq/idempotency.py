"""Two-level idempotency guard.

Semantics follow Java's `RedisStreamIdempotencyGuard`: an in-memory fast path plus
a Redis SETNX placeholder, and — importantly — **fail-open degradation**: when
Redis is unavailable the guard records in memory and allows the message once,
rather than rejecting everything.
"""

from __future__ import annotations

import logging
import threading
import time

from .model import IdempotencyProperties

_log = logging.getLogger(__name__)


class IdempotencyGuard:
    def __init__(
        self,
        client=None,
        properties: IdempotencyProperties | None = None,
        *,
        clock=time.monotonic,
    ) -> None:
        self._client = client
        self._properties = properties if properties is not None else IdempotencyProperties()
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _key(self, raw_key: str) -> str:
        if raw_key is None:
            raise ValueError("rawKey must not be null")
        return f"{self._properties.key_prefix}{raw_key}"

    def try_acquire(self, raw_key: str, ttl_seconds: float | None = None) -> bool:
        """True on first processing, False when the key was already seen."""
        key = self._key(raw_key)
        now = self._clock()
        memory_ttl = self._properties.memory_ttl_seconds
        redis_ttl = self._properties.redis_ttl_seconds if ttl_seconds is None else ttl_seconds

        with self._lock:
            seen_until = self._seen.get(key)
            if seen_until is not None and seen_until > now:
                return False
            self._purge(now)

        if self._client is None:
            with self._lock:
                self._seen[key] = now + memory_ttl
            return True

        try:
            acquired = self._client.set(key, "1", nx=True, ex=max(1, int(redis_ttl)))
        except Exception:  # noqa: BLE001 — fail open, matching Java's degradation
            _log.warning("Idempotency Redis fallback, key=%s", key, exc_info=True)
            with self._lock:
                self._seen[key] = now + memory_ttl
            return True

        with self._lock:
            if acquired:
                self._seen[key] = now + memory_ttl
                return True
            return False

    def release(self, raw_key: str) -> None:
        """Give back a claim so a failed attempt can be retried.

        Without this, acquiring before processing would make every retry look
        like a duplicate and be acked away — retry-to-DLQ could never trigger.
        """
        key = self._key(raw_key)
        with self._lock:
            self._seen.pop(key, None)
        if self._client is not None:
            try:
                self._client.delete(key)
            except Exception:  # noqa: BLE001 — memory claim already released
                _log.warning("Idempotency release failed, key=%s", key, exc_info=True)

    def _purge(self, now: float) -> None:
        for key in [k for k, expiry in self._seen.items() if expiry <= now]:
            del self._seen[key]


__all__ = ["IdempotencyGuard"]
