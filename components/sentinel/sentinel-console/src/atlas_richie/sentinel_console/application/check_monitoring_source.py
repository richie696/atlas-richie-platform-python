"""Application workflow for a session-bound, read-only monitoring probe."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from ..domain.monitoring_sources import (
    MonitoringAuthenticationMode,
    MonitoringSource,
)
from .monitoring_probe import (
    MonitoringProbeCredentials,
    MonitoringProbePort,
    MonitoringProbeResult,
)

MONITORING_CHECK_RECEIPT_TTL = timedelta(minutes=10)
_FINGERPRINT_DOMAIN = b"atlas-richie-sentinel-monitoring-candidate:v1\x00"
_CREDENTIAL_DOMAIN = b"atlas-richie-sentinel-monitoring-credential:v1\x00"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MonitoringSourceCheckReceipt:
    """Persistable safe receipt; no endpoint, query, credential or raw labels."""

    check_id: str
    source_id: str
    source_revision: str
    actor_id: str
    session_digest: str
    candidate_fingerprint: str
    checked_at: datetime
    expires_at: datetime
    result: MonitoringProbeResult

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value or len(value) > 200
            for value in (
                self.check_id,
                self.source_id,
                self.source_revision,
                self.actor_id,
            )
        ):
            raise ValueError("monitoring check receipt identity is invalid")
        if (
            _SHA256_HEX.fullmatch(self.session_digest) is None
            or _SHA256_HEX.fullmatch(self.candidate_fingerprint) is None
        ):
            raise ValueError("monitoring check receipt digest is invalid")
        if (
            self.checked_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.expires_at <= self.checked_at
            or self.expires_at - self.checked_at > MONITORING_CHECK_RECEIPT_TTL
        ):
            raise ValueError("monitoring check receipt expiry is invalid")


class MonitoringProbeReceiptRecorder(Protocol):
    """Durably record a short-lived receipt after a candidate probe completes."""

    async def record_monitoring_probe_receipt(
        self, receipt: MonitoringSourceCheckReceipt
    ) -> None: ...


class MonitoringProbeReceiptReader(Protocol):
    """Read only a still-live receipt owned by the exact authenticated session."""

    async def read_monitoring_probe_receipt(
        self,
        check_id: str,
        *,
        actor_id: str,
        session_digest: str,
        now: datetime,
    ) -> MonitoringSourceCheckReceipt | None: ...


class MonitoringProbeReceiptAuthorityUnavailable(RuntimeError):
    """The Console SQL authority cannot safely record a completed source check."""


@dataclass(frozen=True, slots=True, repr=False)
class CheckMonitoringSourceInput:
    """Candidate plus short-lived resolved credentials, excluded from repr."""

    source: MonitoringSource
    credentials: MonitoringProbeCredentials | None = field(default=None, repr=False)
    credential_reference: str | None = field(default=None, repr=False)


class CheckMonitoringSource:
    """Probe a candidate and bind the result to actor, session and exact inputs."""

    def __init__(
        self,
        probe: MonitoringProbePort,
        recorder: MonitoringProbeReceiptRecorder,
        *,
        fingerprint_key: bytes,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(fingerprint_key, bytes) or len(fingerprint_key) < 32:
            raise ValueError(
                "monitoring fingerprint key must contain at least 32 bytes"
            )
        self._probe = probe
        self._recorder = recorder
        self._fingerprint_key = fingerprint_key
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        command: CheckMonitoringSourceInput,
        *,
        actor_id: str,
        session_digest: str,
    ) -> MonitoringSourceCheckReceipt:
        """Probe without mutating source configuration, then persist safe receipt."""
        if not actor_id or len(actor_id) > 200 or len(session_digest) != 64:
            raise ValueError("monitoring check owner identity is invalid")
        _validate_credentials(
            command.source, command.credentials, command.credential_reference
        )
        result = await self._probe.probe(command.source, command.credentials)
        checked_at = self._now()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("monitoring check clock must return an aware instant")
        fingerprint = monitoring_candidate_fingerprint(
            command.source,
            fingerprint_key=self._fingerprint_key,
            credentials=command.credentials,
            credential_reference=command.credential_reference,
        )
        receipt = MonitoringSourceCheckReceipt(
            check_id=str(uuid4()),
            source_id=command.source.source_id,
            source_revision=command.source.revision,
            actor_id=actor_id,
            session_digest=session_digest,
            candidate_fingerprint=fingerprint,
            checked_at=checked_at,
            expires_at=checked_at + MONITORING_CHECK_RECEIPT_TTL,
            result=result,
        )
        await self._recorder.record_monitoring_probe_receipt(receipt)
        return receipt

def monitoring_candidate_fingerprint(
    source: MonitoringSource,
    *,
    fingerprint_key: bytes,
    credentials: MonitoringProbeCredentials | None,
    credential_reference: str | None,
) -> str:
    """Stable keyed fingerprint shared by check and save boundaries."""
    if not isinstance(fingerprint_key, bytes) or len(fingerprint_key) < 32:
        raise ValueError("monitoring fingerprint key must contain at least 32 bytes")
    credential_payload = json.dumps(
        {
            "username": credentials.username if credentials else None,
            "password": credentials.password if credentials else None,
            "bearerToken": credentials.bearer_token if credentials else None,
            "reference": credential_reference,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    credential_digest = hmac.new(
        fingerprint_key,
        _CREDENTIAL_DOMAIN + credential_payload,
        hashlib.sha256,
    ).hexdigest()
    safe_candidate = {
        "sourceId": source.source_id,
        "revision": source.revision,
        "displayName": source.display_name,
        "environmentId": source.environment_id,
        "endpoint": source.endpoint,
        "provider": source.provider.value,
        "profile": source.profile.value,
        "authenticationMode": source.authentication_mode.value,
        "credentialConfigured": source.credential_configured,
        "enabled": source.enabled,
        "identityLabels": source.identity_labels,
        "selectorLabels": [
            {"name": item.name, "value": item.value}
            for item in source.selector_labels
        ],
        "scrapeIntervalSeconds": source.scrape_interval_seconds,
        "staleAfterSeconds": source.stale_after_seconds,
        "credentialDigest": credential_digest,
    }
    canonical = json.dumps(
        safe_candidate,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hmac.new(
        fingerprint_key,
        _FINGERPRINT_DOMAIN + canonical,
        hashlib.sha256,
    ).hexdigest()


def _validate_credentials(
    source: MonitoringSource,
    credentials: MonitoringProbeCredentials | None,
    reference: str | None = None,
) -> None:
    mode = source.authentication_mode
    if mode is MonitoringAuthenticationMode.NONE:
        valid = credentials is None
    elif mode is MonitoringAuthenticationMode.DIRECT_BASIC:
        valid = (
            credentials is not None
            and credentials.username is not None
            and credentials.password is not None
            and credentials.bearer_token is None
        )
    elif mode is MonitoringAuthenticationMode.DIRECT_BEARER:
        valid = (
            credentials is not None
            and credentials.username is None
            and credentials.password is None
            and credentials.bearer_token is not None
        )
    else:
        # A reference is resolved before the use case; its concrete credential
        # kind may be basic or bearer, but it cannot be an empty result.
        valid = (
            credentials is not None
            and isinstance(reference, str)
            and bool(reference)
            and len(reference) <= 256
        )
    if not valid:
        raise ValueError("monitoring credentials do not match the selected mode")


__all__ = [
    "MONITORING_CHECK_RECEIPT_TTL",
    "CheckMonitoringSource",
    "CheckMonitoringSourceInput",
    "monitoring_candidate_fingerprint",
    "MonitoringProbeReceiptAuthorityUnavailable",
    "MonitoringProbeReceiptReader",
    "MonitoringProbeReceiptRecorder",
    "MonitoringSourceCheckReceipt",
]
