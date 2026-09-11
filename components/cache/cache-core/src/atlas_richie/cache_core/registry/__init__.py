"""Provider-registration SPI + mutex-guarded singleton registry.

Mirrors the Java `ProviderRegistrar` SPI pattern: backends implement
`ProviderRegistrar` and call `CacheRegistry.register(...)` at
startup; the static facade `GlobalCache` reads from the registry
on every call. The second `register()` raises `StateError` — the
caller must `unregister()` first. This enforces "one process, one
provider" at runtime.
"""

from __future__ import annotations

from .cache_registry import CacheRegistry, StateError
from .provider_registrar import ProviderRegistrar

__all__ = ["CacheRegistry", "ProviderRegistrar", "StateError"]
