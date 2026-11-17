"""RFC 6238 TOTP validation and replay prevention, framework-neutral.

Zero runtime dependencies. Storage for replay markers is an injected SPI.
"""

import importlib.metadata

from .engine import TotpProperties, TotpValidationEngine, base32_decode, normalize_algorithm
from .replay import InMemoryReplayGuard, ReplayGuard, ReplayPreventionProperties

__version__ = importlib.metadata.version("atlas-richie-mfa-validation")

__all__ = [
    "InMemoryReplayGuard",
    "ReplayGuard",
    "ReplayPreventionProperties",
    "TotpProperties",
    "TotpValidationEngine",
    "__version__",
    "base32_decode",
    "normalize_algorithm",
]
