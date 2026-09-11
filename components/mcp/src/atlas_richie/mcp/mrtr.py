"""Integrity-protected state for multi-round tool results (MRTR)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import ToolContext


_STATE_VERSION = 1
_MINIMUM_SECRET_BYTES = 32
_DEFAULT_STATE_TTL = timedelta(minutes=5)
_HMAC_DIGEST = hashlib.sha256
_TOKEN_SEPARATOR = "."


class MrtRequestStateError(ValueError):
    """A multi-round state value is malformed, expired, or fails integrity verification."""


@dataclass(frozen=True, slots=True)
class MrtRequestState:
    """The server-owned facts bound to an integrity-protected multi-round request state."""

    resource: str
    principal_fingerprint: str
    tenant_id: str | None
    scopes: frozenset[str]
    registry_revision: int
    expires_at: datetime
    continuation_state: str | None = None

    def __post_init__(self) -> None:
        if not self.resource or not self.principal_fingerprint or self.registry_revision < 0:
            raise ValueError("MRTR state requires resource, principal fingerprint, and a non-negative revision")
        if any(not scope for scope in self.scopes):
            raise ValueError("MRTR scopes must be non-blank")
        if self.continuation_state is not None and not isinstance(self.continuation_state, str):
            raise ValueError("MRTR continuation state must be a string when present")
        expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        object.__setattr__(self, "expires_at", expiry.astimezone(UTC))


class MrtRequestStateCodec:
    """Signs and verifies stateless MRTR state without storing sessions in the MCP core.

    HMAC protects integrity but does not encrypt payload fields; callers must not
    put secrets or sensitive continuation data into this token.
    """

    def __init__(self, signing_secret: bytes, *, ttl: timedelta = _DEFAULT_STATE_TTL) -> None:
        if not isinstance(signing_secret, bytes) or len(signing_secret) < _MINIMUM_SECRET_BYTES:
            raise ValueError(f"MRTR signing_secret must contain at least {_MINIMUM_SECRET_BYTES} bytes")
        if ttl <= timedelta():
            raise ValueError("MRTR ttl must be positive")
        self._signing_secret = signing_secret
        self._ttl = ttl

    def issue(
        self,
        *,
        resource: str,
        principal_fingerprint: str,
        tenant_id: str | None,
        scopes: frozenset[str],
        registry_revision: int,
        continuation_state: str | None = None,
        now: datetime | None = None,
    ) -> str:
        issued_at = _utc_now(now)
        state = MrtRequestState(
            resource=resource,
            principal_fingerprint=principal_fingerprint,
            tenant_id=tenant_id,
            scopes=frozenset(scopes),
            registry_revision=registry_revision,
            expires_at=issued_at + self._ttl,
            continuation_state=continuation_state,
        )
        payload = _encode_payload(state)
        signature = hmac.new(self._signing_secret, payload, _HMAC_DIGEST).digest()
        return f"{_base64url(payload)}{_TOKEN_SEPARATOR}{_base64url(signature)}"

    def verify(self, token: str, *, now: datetime | None = None) -> MrtRequestState:
        if not isinstance(token, str):
            raise MrtRequestStateError("MRTR request state must be a string")
        encoded_payload, separator, encoded_signature = token.partition(_TOKEN_SEPARATOR)
        if not separator or not encoded_payload or not encoded_signature:
            raise MrtRequestStateError("MRTR request state is malformed")
        try:
            payload = _base64url_decode(encoded_payload)
            signature = _base64url_decode(encoded_signature)
        except ValueError as error:
            raise MrtRequestStateError("MRTR request state is malformed") from error
        expected = hmac.new(self._signing_secret, payload, _HMAC_DIGEST).digest()
        if not hmac.compare_digest(signature, expected):
            raise MrtRequestStateError("MRTR request state integrity verification failed")
        state = _decode_payload(payload)
        if state.expires_at <= _utc_now(now):
            raise MrtRequestStateError("MRTR request state has expired")
        return state


class PrincipalFingerprint(Protocol):
    """Application-owned stable, non-secret identity fingerprint for MRTR binding."""

    def __call__(self, context: "ToolContext") -> str: ...


class MrtStateBinding:
    """Binds signed MRTR state to the current security context and registry snapshot."""

    def __init__(self, codec: MrtRequestStateCodec, *, resource: str, principal_fingerprint: PrincipalFingerprint) -> None:
        if not resource.strip():
            raise ValueError("MRTR resource is required")
        self._codec = codec
        self._resource = resource
        self._principal_fingerprint = principal_fingerprint

    def issue(self, context: "ToolContext", *, registry_revision: int, continuation_state: str | None) -> str:
        return self._codec.issue(
            resource=self._resource,
            principal_fingerprint=self._fingerprint(context),
            tenant_id=context.tenant_id,
            scopes=context.granted_scopes,
            registry_revision=registry_revision,
            continuation_state=continuation_state,
        )

    def resume(self, token: str, context: "ToolContext", *, registry_revision: int) -> str | None:
        state = self._codec.verify(token)
        if state.resource != self._resource:
            raise MrtRequestStateError("MRTR request state resource does not match")
        if not hmac.compare_digest(state.principal_fingerprint, self._fingerprint(context)):
            raise MrtRequestStateError("MRTR request state principal does not match")
        if state.tenant_id != context.tenant_id:
            raise MrtRequestStateError("MRTR request state tenant does not match")
        if state.scopes != context.granted_scopes:
            raise MrtRequestStateError("MRTR request state scopes do not match")
        if state.registry_revision != registry_revision:
            raise MrtRequestStateError("MRTR request state registry revision is stale")
        return state.continuation_state

    def _fingerprint(self, context: "ToolContext") -> str:
        value = self._principal_fingerprint(context)
        if not isinstance(value, str) or not value:
            raise ValueError("MRTR principal fingerprint must be a non-empty string")
        return value


def _encode_payload(state: MrtRequestState) -> bytes:
    payload = {
        "v": _STATE_VERSION,
        "resource": state.resource,
        "principal": state.principal_fingerprint,
        "tenant": state.tenant_id,
        "scopes": sorted(state.scopes),
        "revision": state.registry_revision,
        "expiresAt": int(state.expires_at.timestamp()),
        "continuationState": state.continuation_state,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode_payload(payload: bytes) -> MrtRequestState:
    try:
        value: Any = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MrtRequestStateError("MRTR request state payload is invalid") from error
    if not isinstance(value, dict) or value.get("v") != _STATE_VERSION:
        raise MrtRequestStateError("MRTR request state version is unsupported")
    scopes = value.get("scopes")
    expires_at = value.get("expiresAt")
    if (
        not isinstance(value.get("resource"), str)
        or not isinstance(value.get("principal"), str)
        or value.get("tenant") is not None and not isinstance(value.get("tenant"), str)
        or not isinstance(scopes, list)
        or any(not isinstance(scope, str) or not scope for scope in scopes)
        or isinstance(value.get("revision"), bool)
        or not isinstance(value.get("revision"), int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or value.get("continuationState") is not None and not isinstance(value.get("continuationState"), str)
    ):
        raise MrtRequestStateError("MRTR request state payload has an invalid shape")
    return MrtRequestState(
        resource=value["resource"],
        principal_fingerprint=value["principal"],
        tenant_id=value["tenant"],
        scopes=frozenset(scopes),
        registry_revision=value["revision"],
        expires_at=datetime.fromtimestamp(expires_at, UTC),
        continuation_state=value.get("continuationState"),
    )


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except Exception as error:
        raise ValueError("invalid base64url") from error


def _utc_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    return current if current.tzinfo else current.replace(tzinfo=UTC)
