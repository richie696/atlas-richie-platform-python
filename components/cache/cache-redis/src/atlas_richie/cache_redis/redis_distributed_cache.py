"""Real Redis-backed distributed cache wrapper.

Wraps a `redis.Redis` client with:

- A `namespace` prefix on every key (e.g. `atlas-richie:user:42`).
- A `_key(user_key)` method that all managers use to namespaced-key
  before issuing Redis commands.
- Connection-string diagnostics for the `CacheInfrastructure` hook.
- A `close()` hook for graceful shutdown.

The class deliberately does **not** implement any of the cache-core
Protocols (ValueOps, FieldOps, ...); it is a transport-level
abstraction. Each `Redis*Manager` in `managers/` wraps a
`RedisDistributedCache` instance and implements the corresponding
`ProviderRegistrar` accessor.
"""

from __future__ import annotations

from typing import Any, Optional

import redis as redis_lib

from .errors import (
    CacheError,
    ConfigurationError,
    KeyError_,
    StateError,
)


def _default_key_validator(key: str) -> None:
    if not isinstance(key, str) or not key:
        raise KeyError_("cache key must be a non-empty string")
    if len(key) > 512:
        raise KeyError_("cache key exceeds 512 bytes")


class RedisDistributedCache:
    """Production distributed-cache wrapper around `redis-py`.

    Args:
        client: A connected `redis.Redis` instance (caller owns its
            lifecycle; this class never closes it).
        namespace: Prefix prepended to every key with `{namespace}:`.
        key_validator: Optional callable that filters/validates keys
            before they are sent to Redis. The default rejects empty
            keys and keys > 512 bytes.
        connection_string: Human-readable descriptor for logs /
            `CacheInfrastructure.get_connection_string()`. Defaults to
            a short label; pass the real URL when the caller does not
            want the password echoed in logs.
    """

    def __init__(
        self,
        client: Any,
        *,
        namespace: str = "atlas-richie",
        key_validator: Optional[Any] = None,
        connection_string: Optional[str] = None,
    ) -> None:
        if client is None:
            raise ConfigurationError("client is required")
        if not isinstance(namespace, str) or not namespace:
            raise ConfigurationError(
                "RedisDistributedCache.namespace must be a non-empty string"
            )
        self._client = client
        self._namespace = namespace
        self._validate = key_validator or _default_key_validator
        self._connection_string = connection_string or (
            f"redis://{namespace}@<connected>"
        )

    # ── Diagnostics ────────────────────────────────────────────────

    @property
    def namespace(self) -> str:
        return self._namespace

    @property
    def connection_string(self) -> str:
        return self._connection_string

    # ── Key helpers ─────────────────────────────────────────────────

    def make_key(self, key: str) -> str:
        """Apply the namespace prefix to a user-supplied key.

        Raises:
            KeyError_: empty key, wrong type, or exceeding 512 bytes.
        """
        self._validate(key)
        return f"{self._namespace}:{key}"

    # ── Escape hatch ────────────────────────────────────────────────

    def raw_client(self) -> Any:
        """Return the underlying `redis.Redis` instance.

        Use sparingly; prefer the manager-level methods. The returned
        client is **not** namespaced — callers must apply `make_key`
        themselves if they bypass the managers.
        """
        return self._client

    # ── Convenience (used by managers) ──────────────────────────────

    def get(self, key: str) -> Any:
        try:
            return self._client.get(self.make_key(key))
        except Exception as exc:
            raise CacheError(f"Redis GET failed for {key!r}") from exc

    def set(
        self,
        key: str,
        value: bytes | str,
        *,
        ttl_millis: int | None = None,
        if_absent: bool = False,
    ) -> Optional[bool]:
        """Set / set-if-absent with optional TTL in milliseconds.

        Returns:
            - `True` on success (the key was set, with or without NX).
            - `False` when `if_absent=True` and the key already exists.
            - `None` when `if_absent=False` (no NX semantics to report).
        """
        full_key = self.make_key(key)
        kwargs: dict[str, Any] = {}
        if ttl_millis is not None and ttl_millis > 0:
            kwargs["px"] = int(ttl_millis)
        try:
            if if_absent:
                result = self._client.set(full_key, value, nx=True, **kwargs)
            else:
                result = self._client.set(full_key, value, **kwargs)
        except Exception as exc:
            raise CacheError(f"Redis SET failed for {key!r}") from exc
        # `redis-py` returns `True` (or `b'OK'` with `decode_responses=False`)
        # on success and `None` on NX failure. Treat both success markers
        # as truthy.
        if if_absent:
            return bool(result)
        return None

    def delete(self, key: str) -> int:
        try:
            return int(self._client.delete(self.make_key(key)))
        except Exception as exc:
            raise CacheError(f"Redis DEL failed for {key!r}") from exc

    def exists(self, key: str) -> bool:
        try:
            return bool(self._client.exists(self.make_key(key)))
        except Exception as exc:
            raise CacheError(f"Redis EXISTS failed for {key!r}") from exc

    def ttl_seconds(self, key: str) -> int:
        try:
            return int(self._client.ttl(self.make_key(key)))
        except Exception as exc:
            raise CacheError(f"Redis TTL failed for {key!r}") from exc

    def expire(self, key: str, ttl_millis: int) -> bool:
        if ttl_millis <= 0:
            raise ConfigurationError("ttl_millis must be positive")
        try:
            return bool(self._client.pexpire(self.make_key(key), int(ttl_millis)))
        except Exception as exc:
            raise CacheError(f"Redis PEXPIRE failed for {key!r}") from exc

    def keys(self, pattern: str = "*") -> list[str]:
        """Return all keys matching `pattern` (post-namespace strip).

        Uses `SCAN` (cursor-based, non-blocking) instead of `KEYS` so
        the call is safe in production. Returns a list of unprefixed
        user keys.
        """
        prefix = f"{self._namespace}:"
        full_pattern = self.make_key(pattern)
        out: list[str] = []
        try:
            for raw in self._client.scan_iter(match=full_pattern, count=200):
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                if raw.startswith(prefix):
                    out.append(raw[len(prefix):])
        except Exception as exc:
            raise CacheError(
                f"Redis SCAN failed for {pattern!r}: {exc}"
            ) from exc
        return out

    def close(self) -> None:
        """Close the underlying connection (best-effort)."""
        client = self._client
        # `redis.Redis.close()` is async-friendly; on the sync client
        # it just closes the pool.
        close = getattr(client, "close", None)
        if close is None:
            return
        try:
            close()
        except Exception as exc:
            raise StateError(f"Error closing redis client: {exc}") from exc

    def __repr__(self) -> str:
        return (
            f"RedisDistributedCache(namespace={self._namespace!r}, "
            f"client={type(self._client).__name__})"
        )


# Re-export the underlying `redis` package so backend consumers can
# `from atlas_richie.cache_redis.redis_distributed_cache import redis`
# without an extra import. (We do not expose this at the package
# level — it is purely a back-compat convenience for tests.)
__all__ = ["RedisDistributedCache", "redis_lib"]
