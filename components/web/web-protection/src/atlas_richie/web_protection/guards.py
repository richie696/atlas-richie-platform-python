"""Request guards: payload size limits and HMAC request signing.

Ported from `RequestSizeGuard` and the algorithm inside `ApiSignatureInterceptor`
(Java). The servlet interceptor shell, chain plumbing and `ApiResult` body
rendering are adapter concerns and are deliberately not ported: these classes
return decisions and leave rendering to the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Protocol

from .trackers import NonceCache

HEADER_TIMESTAMP = "X-Timestamp"
HEADER_NONCE = "X-Nonce"
HEADER_SIGNATURE = "X-Signature"

# HTTP/1.1 approximation: `name + ": " + value + "\r\n"` overhead per header line.
_HEADER_LINE_OVERHEAD = 4


class RequestContext(Protocol):
    """Minimal read-only request view, so no web framework types leak in."""

    def header(self, name: str) -> str | None: ...

    def header_names(self) -> list[str]: ...

    def headers(self, name: str) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class RequestSizeDecision:
    status: int
    reason: str
    limit: int
    actual: int


class RequestSizeGuard:
    """Denies oversized bodies or header blocks; body is checked first."""

    def __init__(
        self,
        max_body_bytes: int,
        max_header_bytes: int,
        body_deny_status: int = 413,
        header_deny_status: int = 431,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError(f"maxBodyBytes must be > 0, got: {max_body_bytes}")
        if max_header_bytes <= 0:
            raise ValueError(f"maxHeaderBytes must be > 0, got: {max_header_bytes}")
        self._max_body = max_body_bytes
        self._max_header = max_header_bytes
        self._body_status = body_deny_status
        self._header_status = header_deny_status

    def check(self, ctx: RequestContext) -> RequestSizeDecision | None:
        return self._check_body(ctx) or self._check_headers(ctx)

    def _check_body(self, ctx: RequestContext) -> RequestSizeDecision | None:
        raw = ctx.header("Content-Length")
        if raw is None or not raw.strip():
            return None
        try:
            body_bytes = int(raw.strip())
        except ValueError:
            return None  # unparseable Content-Length passes through, as in Java
        if body_bytes < 0:
            return None
        if body_bytes > self._max_body:
            return RequestSizeDecision(
                self._body_status, "REQUEST_BODY_TOO_LARGE", self._max_body, body_bytes
            )
        return None

    def _check_headers(self, ctx: RequestContext) -> RequestSizeDecision | None:
        total = 0
        for name in ctx.header_names():
            for value in ctx.headers(name):
                # Character counts, matching the Java approximation (not UTF-8 bytes).
                total += len(name) + len(value) + _HEADER_LINE_OVERHEAD
        if total > self._max_header:
            return RequestSizeDecision(
                self._header_status, "REQUEST_HEADER_TOO_LARGE", self._max_header, total
            )
        return None


class SecretKeyProvider(Protocol):
    """Loads the shared secret for a client key (Vault / DB / config)."""

    def secret_for(self, client_key: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class SignatureDecision:
    reason: str
    client_key: str | None


def canonicalize(method: str, path: str, timestamp: int, nonce: str) -> str:
    return f"{method}\n{path}\n{timestamp}\n{nonce}"


def hmac_sha256_hex(secret: bytes, message: str) -> str:
    """Lower-case hex, matching Java's `HexFormat.of().formatHex`."""
    return hmac.new(secret, message.encode("utf-8"), hashlib.sha256).hexdigest()


class ApiSignatureVerifier:
    """Validates timestamp skew, nonce replay and the HMAC-SHA256 signature.

    Returns None to allow, or a `SignatureDecision` naming the deny reason.
    Reason strings and their evaluation order match the Java interceptor.
    """

    def __init__(
        self,
        key_provider: SecretKeyProvider,
        nonce_cache: NonceCache,
        timestamp_skew_seconds: float,
        *,
        clock=time.time,
    ) -> None:
        self._key_provider = key_provider
        self._nonce_cache = nonce_cache
        self._skew_millis = timestamp_skew_seconds * 1000.0
        self._clock = clock

    def verify(
        self,
        *,
        method: str,
        path: str,
        client_key: str | None,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
        gateway_bypassed: bool = False,
        now_millis: int | None = None,
    ) -> SignatureDecision | None:
        if gateway_bypassed:
            return None
        if client_key is None or not client_key.strip():
            return None
        if timestamp is None:
            return SignatureDecision("missing_header", client_key)
        try:
            ts = int(timestamp)
        except ValueError:
            return SignatureDecision("bad_timestamp", client_key)
        now = now_millis if now_millis is not None else int(self._clock() * 1000)
        if abs(now - ts) > self._skew_millis:
            return SignatureDecision("timestamp_skew", client_key)
        if nonce is None:
            return SignatureDecision("missing_header", client_key)
        if not self._nonce_cache.put_if_absent(nonce):
            return SignatureDecision("nonce_replay", client_key)
        if signature is None:
            return SignatureDecision("missing_header", client_key)
        secret = self._key_provider.secret_for(client_key)
        if not secret:
            return SignatureDecision("no_secret", client_key)
        expected = hmac_sha256_hex(secret, canonicalize(method, path, ts, nonce))
        if not hmac.compare_digest(expected, signature):
            return SignatureDecision("signature_mismatch", client_key)
        return None


__all__ = [
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "ApiSignatureVerifier",
    "RequestContext",
    "RequestSizeDecision",
    "RequestSizeGuard",
    "SecretKeyProvider",
    "SignatureDecision",
    "canonicalize",
    "hmac_sha256_hex",
]
