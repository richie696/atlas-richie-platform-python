"""Stable framework-neutral contracts for Atlas Richie components."""

from .capability import CapabilityDescriptor
from .errors import CapabilityUnavailable, PlatformError, ValidationError
from .lifecycle import AsyncCloseable

__all__ = [
    "AsyncCloseable",
    "CapabilityDescriptor",
    "CapabilityUnavailable",
    "PlatformError",
    "ValidationError",
]
