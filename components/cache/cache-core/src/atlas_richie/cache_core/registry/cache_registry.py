"""Process-wide cache provider registry (mutual-exclusion enforced).

`CacheRegistry` is the framework's "one process, one provider" gate.
Backends register themselves here at startup; the static facade
`GlobalCache` reads from here. Registering a second provider while
one is already active raises `StateError` — the caller must call
`unregister()` first to swap backends. This is deliberate: silently
overwriting the active provider would let one component tear down
another component's Redis client out from under it.

Thread-safety: a single class-level `Lock` guards both reads and
writes of `_registrar`. Reads (`active()`, `is_registered()`) acquire
the lock too, so a swap cannot be observed mid-flight. The lock is
held only for the duration of the assignment / lookup, not for any
user-level operation; cap latency is bounded by Lock acquire +
attribute write.

Why classmethods (not instance + Holder pattern)? Because the
registry is itself process-wide state; there's no value in
instantiating it. A static class is the most honest expression of
that.

Diagnostics: `active_provider()` returns the enum of the active
provider (or `None` if uninitialized) for logs / health checks.
"""

from __future__ import annotations

import threading
from typing import ClassVar, Optional

from ..enums.cache_provider import CacheProvider
from .provider_registrar import ProviderRegistrar


class StateError(RuntimeError):
    """Raised when the registry is in a state that prevents the
    requested operation (already-registered, not-registered, ...)."""


class CacheRegistry:
    """Mutex-guarded singleton for the active `ProviderRegistrar`."""

    _registrar: ClassVar[Optional[ProviderRegistrar]] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def register(cls, registrar: ProviderRegistrar) -> None:
        """Install `registrar` as the active provider.

        Raises:
            StateError: another provider is already registered. Call
                :meth:`unregister` first to swap backends.
        """
        with cls._lock:
            if cls._registrar is not None:
                active_kind = cls._registrar.provider()
                new_kind = registrar.provider()
                raise StateError(
                    f"Cache provider already registered ({active_kind!r}). "
                    f"Call CacheRegistry.unregister() first to switch "
                    f"to {new_kind!r}."
                )
            cls._registrar = registrar

    @classmethod
    def unregister(cls) -> None:
        """Drop the active provider. No-op if none was registered.

        The caller is responsible for closing the previous provider's
        resources (e.g. Redis connection); the registry only drops
        its reference.
        """
        with cls._lock:
            cls._registrar = None

    @classmethod
    def active(cls) -> ProviderRegistrar:
        """Return the active `ProviderRegistrar`.

        Raises:
            StateError: no provider is currently registered. Call
                :meth:`register` (or `GlobalCache.install(...)`) first.
        """
        with cls._lock:
            if cls._registrar is None:
                raise StateError(
                    "No cache provider registered. "
                    "Call GlobalCache.install(registrar) first."
                )
            return cls._registrar

    @classmethod
    def is_registered(cls) -> bool:
        """True if a provider is currently registered."""
        with cls._lock:
            return cls._registrar is not None

    @classmethod
    def active_provider(cls) -> Optional[CacheProvider]:
        """Return the active provider's enum (or `None`)."""
        with cls._lock:
            return cls._registrar.provider() if cls._registrar else None


__all__ = ["CacheRegistry", "StateError"]
