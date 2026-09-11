"""Stable error categories without transport or framework coupling."""


class PlatformError(Exception):
    """Base exception for expected, portable component failures."""


class ValidationError(PlatformError):
    """Raised when public input does not meet a component contract."""


class CapabilityUnavailable(PlatformError):
    """Raised when an optional adapter or configured capability is absent."""
