"""RFC 6238 TOTP validation engine.

Ported from `cn.richie696.component.mfa.validation.engine.TotpValidationEngine`
(Java). Standard library only: `hmac`, `hashlib`, `base64`, `struct`.

Security behaviour preserved from the Java side:
- verification is fail-closed: any internal error returns False, never raises;
- neither the secret nor the submitted code is ever logged (only the exception
  type), so logs cannot leak credentials.

Deliberate Python deviation: `now` can be injected for deterministic tests and
for callers that already hold a request timestamp. Java reads `Instant.now()`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import struct
import time
from dataclasses import dataclass

_log = logging.getLogger(__name__)

_SUPPORTED_ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}


@dataclass(frozen=True, slots=True)
class TotpProperties:
    """Defaults used when a caller does not supply per-user period/digits."""

    time_window: int = 30
    code_length: int = 6
    algorithm: str = "SHA1"


def normalize_algorithm(algorithm: str | None, configured_default: str | None = None) -> str:
    """Resolve an algorithm name, stripping a `Hmac` prefix and falling back.

    Priority: explicit argument, then configured default, then SHA1 (RFC 6238).
    An unrecognised value never raises; it falls through to the default.
    """
    for candidate in (algorithm, configured_default):
        if candidate:
            normalized = candidate.removeprefix("Hmac").upper()
            if normalized in _SUPPORTED_ALGORITHMS:
                return normalized
    return "SHA1"


def base32_decode(encoded: str) -> bytes:
    """Lenient Base32 decoding matching Apache Commons Codec's `new Base32()`.

    Tolerates lower case, embedded whitespace and missing `=` padding, all of
    which appear in manually-entered or QR-scanned secrets.
    """
    cleaned = "".join(encoded.split()).upper().rstrip("=")
    if not cleaned:
        return b""
    padded = cleaned + "=" * (-len(cleaned) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Base32解码失败") from error


class TotpValidationEngine:
    """Generates and verifies TOTP codes over a ±window tolerance."""

    def __init__(self, properties: TotpProperties | None = None) -> None:
        self._properties = properties if properties is not None else TotpProperties()

    @property
    def properties(self) -> TotpProperties:
        return self._properties

    def generate_code(
        self,
        secret: str,
        time_step: int,
        digits: int | None = None,
        algorithm: str | None = None,
    ) -> str:
        """RFC 6238: Base32 secret, 8-byte big-endian counter, HMAC, truncation.

        Raises ValueError on an undecodable secret; `verify_code` catches that
        and fails closed.
        """
        digits = digits if digits is not None else self._properties.code_length
        resolved = normalize_algorithm(algorithm, self._properties.algorithm)
        key = base32_decode(secret)
        data = struct.pack(">q", time_step)
        digest = hmac.new(key, data, _SUPPORTED_ALGORITHMS[resolved]).digest()
        offset = digest[-1] & 0x0F
        binary = (
            ((digest[offset] & 0x7F) << 24)
            | ((digest[offset + 1] & 0xFF) << 16)
            | ((digest[offset + 2] & 0xFF) << 8)
            | (digest[offset + 3] & 0xFF)
        )
        otp = binary % (10 ** digits)
        return str(otp).zfill(digits)

    def verify_code(
        self,
        plain_secret: str | None,
        code: str | None,
        window: int = 1,
        algorithm: str | None = None,
        period: int | None = None,
        digits: int | None = None,
        *,
        now: int | None = None,
    ) -> bool:
        """True when `code` matches any step in `[current - window, current + window]`.

        `period` / `digits` override the configured defaults so verification uses
        the same parameters the provisioning QR code was generated with.
        """
        try:
            if plain_secret is None or not plain_secret.strip():
                return False
            if code is None:
                return False
            resolved = normalize_algorithm(algorithm, self._properties.algorithm)
            step_seconds = period if period is not None else self._properties.time_window
            if step_seconds <= 0:
                return False
            code_length = digits if digits is not None else self._properties.code_length
            unix_seconds = int(now if now is not None else time.time())
            current_step = unix_seconds // step_seconds
            for delta in range(-window, window + 1):
                generated = self.generate_code(
                    plain_secret, current_step + delta, code_length, resolved
                )
                if hmac.compare_digest(generated, code):
                    return True
            return False
        except Exception as error:  # noqa: BLE001 — fail closed, never leak values
            _log.error("TOTP verification failed; exceptionType=%s", type(error).__name__)
            return False


__all__ = ["TotpProperties", "TotpValidationEngine", "base32_decode", "normalize_algorithm"]
