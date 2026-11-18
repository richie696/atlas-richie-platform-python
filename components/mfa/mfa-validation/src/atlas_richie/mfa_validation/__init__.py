"""RFC 6238 TOTP validation and replay prevention, framework-neutral.

Zero runtime dependencies. Storage for replay markers is an injected SPI.
"""

import importlib.metadata

from .enrollment import (
    SECRET_KEY_LENGTH,
    generate_qr_code_url,
    generate_secret_key,
)
from .engine import TotpProperties, TotpValidationEngine, base32_decode, normalize_algorithm
from .replay import InMemoryReplayGuard, ReplayGuard, ReplayPreventionProperties
from .service import (
    ENABLED,
    DefaultMfaValidationService,
    InMemoryMfaStateStore,
    InMemoryTrustedDeviceStore,
    MfaSecurityProperties,
    MfaStateStore,
    MfaUserInfo,
    MfaValidationProperties,
    MfaValidationResult,
    SecretRetriever,
    TrustedDeviceProperties,
    TrustedDeviceStore,
)

__version__ = importlib.metadata.version("atlas-richie-mfa-validation")

__all__ = [
    "SECRET_KEY_LENGTH",
    "generate_secret_key",
    "generate_qr_code_url",
    "ENABLED",
    "DefaultMfaValidationService",
    "InMemoryMfaStateStore",
    "InMemoryReplayGuard",
    "InMemoryTrustedDeviceStore",
    "MfaSecurityProperties",
    "MfaStateStore",
    "MfaUserInfo",
    "MfaValidationProperties",
    "MfaValidationResult",
    "ReplayGuard",
    "ReplayPreventionProperties",
    "SecretRetriever",
    "TotpProperties",
    "TotpValidationEngine",
    "TrustedDeviceProperties",
    "TrustedDeviceStore",
    "__version__",
    "base32_decode",
    "normalize_algorithm",
]
