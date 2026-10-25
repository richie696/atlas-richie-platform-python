"""Application-owned persistence contract for monitoring source configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .check_monitoring_source import monitoring_candidate_fingerprint
from ..domain.monitoring_sources import MonitoringSource, MonitoringSourcesSnapshot
from .monitoring_probe import MonitoringProbeCredentials


class MonitoringSourceRegistryUnavailable(RuntimeError):
    """The authoritative monitoring-source SQL store is unavailable or corrupt."""


class MonitoringSourceNotFound(LookupError):
    """No source with the requested stable ID exists."""


class MonitoringSourceRevisionConflict(RuntimeError):
    """The stored source revision no longer matches the operator's read revision."""


class MonitoringSourceOperationStatus(StrEnum):
    """Finite durable outcomes for a source-management command."""

    COMPLETED = "completed"
    REJECTED = "rejected"


class MonitoringSourceOperationReason(StrEnum):
    """Safe rejection classes that never include provider or credential text."""

    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    CHECK_REQUIRED = "check_required"
    CHECK_MISMATCH = "check_mismatch"
    SOURCE_IN_USE = "source_in_use"


class MonitoringSourceCommandForbidden(RuntimeError):
    """The command receipt belongs to another account or authenticated session."""


class MonitoringSourceIdempotencyConflict(RuntimeError):
    """An idempotency key was reused for different command content."""


class MonitoringSourceCommandUnavailable(RuntimeError):
    """The SQL command authority cannot commit or recover the operation."""


class MonitoringCredentialUpdateMode(StrEnum):
    """Explicit update intent prevents an omitted secret from being ambiguous."""

    KEEP = "keep"
    REPLACE = "replace"
    CLEAR = "clear"


@dataclass(frozen=True, slots=True, repr=False)
class MonitoringSourceMutation:
    """One bounded create/update/delete command; secret values never appear in repr."""

    request_key: str
    kind: str
    actor_id: str
    session_digest: str
    request_id: str
    source: MonitoringSource | None = None
    source_id: str | None = None
    expected_revision: str | None = None
    credential_update: MonitoringCredentialUpdateMode | None = None
    secret: MonitoringSourceSecret | None = field(default=None, repr=False)
    check_id: str | None = None
    candidate_fingerprint: str | None = field(default=None, repr=False)
    skip_check: bool = False
    enabled: bool | None = None
    now: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"create", "update", "delete", "set-enabled"}:
            raise ValueError("monitoring source command kind is invalid")
        for value in (self.request_key, self.actor_id, self.request_id):
            if not isinstance(value, str) or not value or len(value) > 200:
                raise ValueError("monitoring source command identity is invalid")
        if len(self.session_digest) != 64:
            raise ValueError("monitoring source command session is invalid")
        if type(self.skip_check) is not bool:
            raise ValueError("monitoring source command check policy is invalid")
        if self.kind in {"delete", "set-enabled"}:
            if (
                self.source is not None
                or self.secret is not None
                or self.credential_update is not None
                or self.check_id is not None
                or self.skip_check
                or not self.source_id
                or not self.expected_revision
                or (self.kind == "delete" and self.enabled is not None)
                or (self.kind == "set-enabled" and type(self.enabled) is not bool)
            ):
                raise ValueError("monitoring source metadata command is inconsistent")
        else:
            if (
                self.source is None
                or self.source_id is not None
                or self.credential_update is None
                or (self.check_id is None) == (not self.skip_check)
                or (
                    self.kind == "create" and self.expected_revision is not None
                )
                or (
                    self.kind == "update"
                    and self.expected_revision != self.source.revision
                )
                or self.enabled is not None
            ):
                raise ValueError("monitoring source upsert command is inconsistent")
        if self.now is not None and (
            self.now.tzinfo is None or self.now.utcoffset() is None
        ):
            raise ValueError("monitoring source command time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ManageMonitoringSource:
    """Fingerprint request-local credentials, then execute one durable command."""

    registry: MonitoringSourceRegistryPort
    fingerprint_key: bytes = field(repr=False)

    async def execute(
        self,
        command: MonitoringSourceMutation,
    ) -> MonitoringSourceOperation:
        if command.source is None:
            return await self.registry.execute_monitoring_source_mutation(command)
        secret = command.secret
        credentials = None
        reference = None
        if secret is not None:
            if secret.username is not None:
                credentials = MonitoringProbeCredentials(
                    username=secret.username, password=secret.password
                )
            elif secret.bearer_token is not None:
                credentials = MonitoringProbeCredentials(
                    bearer_token=secret.bearer_token
                )
            reference = secret.credential_reference
        fingerprint = monitoring_candidate_fingerprint(
            command.source,
            fingerprint_key=self.fingerprint_key,
            credentials=credentials,
            credential_reference=reference,
        )
        return await self.registry.execute_monitoring_source_mutation(
            MonitoringSourceMutation(
                request_key=command.request_key,
                kind=command.kind,
                actor_id=command.actor_id,
                session_digest=command.session_digest,
                request_id=command.request_id,
                source=command.source,
                expected_revision=command.expected_revision,
                credential_update=command.credential_update,
                secret=command.secret,
                check_id=command.check_id,
                skip_check=command.skip_check,
                candidate_fingerprint=fingerprint,
                now=command.now,
                enabled=command.enabled,
            )
        )


@dataclass(frozen=True, slots=True)
class MonitoringSourceOperation:
    """Durable safe operation receipt; contains no endpoint or secret material."""

    request_key: str
    status: MonitoringSourceOperationStatus
    source_id: str | None = None
    source_revision: str | None = None
    enabled: bool | None = None
    verified: bool | None = None
    reason: MonitoringSourceOperationReason | None = None

    def __post_init__(self) -> None:
        if not self.request_key:
            raise ValueError("monitoring source operation key is invalid")
        if (self.status is MonitoringSourceOperationStatus.COMPLETED) != (
            self.source_id is not None
        ):
            raise ValueError("monitoring source operation result is inconsistent")
        if (self.status is MonitoringSourceOperationStatus.REJECTED) != (
            self.reason is not None
        ):
            raise ValueError("monitoring source operation reason is inconsistent")


@dataclass(frozen=True, slots=True, repr=False)
class MonitoringSourceSecret:
    """Ephemeral source authentication data; never part of safe read DTOs."""

    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    bearer_token: str | None = field(default=None, repr=False)
    credential_reference: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        supplied = sum(
            value is not None
            for value in (
                self.username,
                self.password,
                self.bearer_token,
                self.credential_reference,
            )
        )
        if supplied == 0:
            raise ValueError("monitoring secret material cannot be empty")
        if (self.username is None) != (self.password is None):
            raise ValueError("monitoring basic credentials are incomplete")
        for value in (
            self.username,
            self.password,
            self.bearer_token,
            self.credential_reference,
        ):
            if value is not None and (
                not isinstance(value, str)
                or not value
                or len(value) > 4096
                or any(character in value for character in "\r\n\x00")
            ):
                raise ValueError("monitoring secret material is invalid")
        if supplied > 2 or (self.bearer_token is not None and supplied != 1):
            raise ValueError("monitoring secret material has conflicting modes")


class MonitoringSourceRegistryPort(Protocol):
    """Minimum SQL-backed source registry capability consumed by the app."""

    async def read_monitoring_sources(self) -> MonitoringSourcesSnapshot: ...

    async def read_monitoring_source(self, source_id: str) -> MonitoringSource: ...

    async def create_monitoring_source(
        self,
        source: MonitoringSource,
        *,
        secret: MonitoringSourceSecret | None,
        now: datetime,
    ) -> MonitoringSource: ...

    async def update_monitoring_source(
        self,
        source: MonitoringSource,
        *,
        expected_revision: str,
        credential_update: MonitoringCredentialUpdateMode,
        secret: MonitoringSourceSecret | None,
        now: datetime,
    ) -> MonitoringSource: ...

    async def delete_monitoring_source(
        self,
        source_id: str,
        *,
        expected_revision: str,
        now: datetime,
    ) -> None: ...

    async def resolve_monitoring_source_secret(
        self, source_id: str, *, expected_revision: str
    ) -> MonitoringSourceSecret | None: ...

    async def execute_monitoring_source_mutation(
        self, command: MonitoringSourceMutation
    ) -> MonitoringSourceOperation: ...

    async def read_monitoring_source_operation(
        self, request_key: str, *, actor_id: str, session_digest: str
    ) -> MonitoringSourceOperation | None: ...


@dataclass(frozen=True, slots=True)
class ReadMonitoringSources:
    """Read the authoritative bounded list without exposing credential values."""

    registry: MonitoringSourceRegistryPort

    async def execute(self) -> MonitoringSourcesSnapshot:
        return await self.registry.read_monitoring_sources()


@dataclass(frozen=True, slots=True)
class ReadMonitoringSource:
    """Read one safe configuration view; secret values remain write-only."""

    registry: MonitoringSourceRegistryPort

    async def execute(self, source_id: str) -> MonitoringSource:
        return await self.registry.read_monitoring_source(source_id)


__all__ = [
    "MonitoringCredentialUpdateMode",
    "MonitoringSourceCommandForbidden",
    "MonitoringSourceCommandUnavailable",
    "MonitoringSourceIdempotencyConflict",
    "MonitoringSourceNotFound",
    "MonitoringSourceMutation",
    "MonitoringSourceOperation",
    "MonitoringSourceOperationReason",
    "MonitoringSourceOperationStatus",
    "ManageMonitoringSource",
    "MonitoringSourceRegistryPort",
    "MonitoringSourceRegistryUnavailable",
    "MonitoringSourceRevisionConflict",
    "MonitoringSourceSecret",
    "ReadMonitoringSource",
    "ReadMonitoringSources",
]
