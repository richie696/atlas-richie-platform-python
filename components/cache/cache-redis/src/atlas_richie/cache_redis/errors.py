"""Cache-redis failure types.

All errors inherit from `atlas_richie.contracts.PlatformError` so the
core contract is the same as the rest of the platform.
"""

from __future__ import annotations

from atlas_richie.contracts import PlatformError


class CacheError(PlatformError):
    """Base class for controlled cache failures (Redis backend)."""


class ConfigurationError(CacheError):
    """Cache configuration is invalid (missing URL, bad TTL, etc.)."""


class ConnectionError(CacheError):
    """The Redis backend is unreachable."""


class SerializationError(CacheError):
    """A value could not be (de)serialised to/from bytes/JSON."""


class KeyError_(CacheError):
    """A cache key is invalid (empty, too long, or wrong type)."""


class CapacityError(CacheError):
    """A bounded structure has reached or exceeded its capacity limits."""


class ConflictError(CacheError):
    """A set-if-absent / lock-acquire observed a competing state it could not resolve."""


class StateError(CacheError):
    """The cache or a sub-component is in an invalid state for the requested operation."""


__all__ = [
    "CacheError",
    "CapacityError",
    "ConfigurationError",
    "ConflictError",
    "ConnectionError",
    "KeyError_",
    "SerializationError",
    "StateError",
]
