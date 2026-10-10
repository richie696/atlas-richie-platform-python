"""Application contract for checking an admin-managed source without writes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from math import isfinite
from time import perf_counter_ns
from typing import Callable, Protocol

from ..domain.configuration_source import ConfigurationSourceProvider
from .source_credential_references import (
    ResolvedSourceCredentials,
    SourceCredentialReferenceResolver,
)
from .registered_source_ports import RegisteredSourceProbeRecorder


class SourceCheckAuthenticationMode(StrEnum):
    """Authentication input choices for a source check."""

    NONE = "none"
    CREDENTIAL_REFERENCE = "credential-reference"
    DIRECT = "direct"
    KEEP = "keep"


class SourceCheckFailureReason(StrEnum):
    """Finite reasons safe to show for an unsuccessful check."""

    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    UNSUPPORTED = "unsupported"


class SourceCheckCapability(StrEnum):
    """Capabilities demonstrated by a non-mutating source probe."""

    READ = "read"
    CONDITIONAL_WRITE = "conditional-write"
    WATCH = "watch"


@dataclass(frozen=True, slots=True)
class SourceConnectionInput:
    """Ephemeral provider connection input; secrets are write-only."""

    source_id: str | None
    expected_revision: str | None
    provider: ConfigurationSourceProvider
    endpoint: str
    location: str
    authentication_mode: SourceCheckAuthenticationMode
    credential_reference: str | None = field(default=None, repr=False, compare=False)
    username: str | None = field(default=None, repr=False, compare=False)
    password: str | None = field(default=None, repr=False, compare=False)
    acl_token: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (self.source_id is None) != (self.expected_revision is None):
            raise ValueError(
                "source identity and expected revision must appear together"
            )
        if self.authentication_mode is SourceCheckAuthenticationMode.KEEP:
            if self.source_id is None or self._has_secret():
                raise ValueError("keeping credentials requires an existing source only")
        elif self.authentication_mode is SourceCheckAuthenticationMode.NONE:
            if self._has_secret():
                raise ValueError("no-auth checks cannot carry credential fields")
        elif (
            self.authentication_mode
            is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
        ):
            if not self.credential_reference:
                raise ValueError("credential-reference checks require a reference")
            if any(
                value is not None
                for value in (self.username, self.password, self.acl_token)
            ):
                raise ValueError(
                    "credential-reference mode has no direct secret fields"
                )
        elif self.authentication_mode is SourceCheckAuthenticationMode.DIRECT:
            if self.credential_reference is not None:
                raise ValueError("direct authentication cannot carry a reference")
            if self.provider is ConfigurationSourceProvider.NACOS:
                valid = bool(self.username and self.password) and self.acl_token is None
            else:
                valid = (
                    bool(self.acl_token)
                    and self.username is None
                    and self.password is None
                )
            if not valid:
                raise ValueError("direct credentials do not match source provider")
        else:
            raise ValueError("source authentication mode is invalid")

    def _has_secret(self) -> bool:
        return any(
            value is not None
            for value in (
                self.credential_reference,
                self.username,
                self.password,
                self.acl_token,
            )
        )


@dataclass(frozen=True, slots=True)
class RegisteredSourceCheckResult:
    """Short-lived, bounded source check fact for the operator UI."""

    checked_at: datetime
    expires_at: datetime
    capabilities: tuple[SourceCheckCapability, ...] = ()
    reason: SourceCheckFailureReason | None = None
    latency_ms: float | None = None

    def __post_init__(self) -> None:
        if (
            self.checked_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.expires_at <= self.checked_at
        ):
            raise ValueError("source check timestamps must be ordered aware instants")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("source check capabilities must be unique")
        if self.reason is None and not self.capabilities:
            raise ValueError("reachable source checks must report a capability")
        if self.reason is not None and self.capabilities:
            raise ValueError("unreachable source checks cannot report capabilities")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not isfinite(self.latency_ms)
            or self.latency_ms < 0
        ):
            raise ValueError("source check latency must be non-negative")

    @property
    def reachable(self) -> bool:
        """Whether the source was reached with at least one usable capability."""
        return self.reason is None


class RegisteredSourceCheckUnavailable(RuntimeError):
    """The source-check authority cannot provide a trustworthy result."""


class RegisteredSourceCredentialsUnavailable(RuntimeError):
    """Stored credentials cannot be resolved for the requested source revision."""


class RegisteredSourceCheckRateLimited(RuntimeError):
    """The source-check authority rejected the request due to rate limits."""

    def __init__(self, retry_after_ms: int) -> None:
        if type(retry_after_ms) is not int or not 0 <= retry_after_ms <= 300_000:
            raise ValueError("retry delay must be bounded")
        self.retry_after_ms = retry_after_ms
        super().__init__("source check rate limited")


class RegisteredSourceChecker(Protocol):
    """Perform a bounded, read-only probe with resolved ephemeral connection input."""

    async def check(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        """Check access/capabilities without registration or rule publication."""


class RegisteredSourceCredentialResolver(Protocol):
    """Resolve only the encrypted credentials for one exact stored revision."""

    async def resolve_credentials(
        self,
        source_id: str,
        expected_revision: str,
        provider: ConfigurationSourceProvider,
    ) -> SourceConnectionInput | None:
        """Return ephemeral credentials or None when identity/revision is stale."""


class CheckRegisteredSource:
    """Resolve ephemeral credentials, then delegate one non-mutating source probe."""

    def __init__(
        self,
        checker: RegisteredSourceChecker,
        credential_resolver: RegisteredSourceCredentialResolver | None,
        credential_reference_resolver: SourceCredentialReferenceResolver | None = None,
        probe_recorder: RegisteredSourceProbeRecorder | None = None,
        monotonic_ns: Callable[[], int] = perf_counter_ns,
    ) -> None:
        self._checker = checker
        self._credential_resolver = credential_resolver
        self._credential_reference_resolver = credential_reference_resolver
        self._probe_recorder = probe_recorder
        self._monotonic_ns = monotonic_ns

    async def execute(
        self, command: SourceConnectionInput, actor_id: str
    ) -> RegisteredSourceCheckResult:
        """Use current form coordinates with credentials from the exact stored revision."""
        connection = command
        if (
            command.authentication_mode
            is SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
        ):
            connection = await self._resolve_reference(command)
        elif command.authentication_mode is SourceCheckAuthenticationMode.KEEP:
            if (
                self._credential_resolver is None
                or command.source_id is None
                or command.expected_revision is None
            ):
                raise RegisteredSourceCheckUnavailable(
                    "registered source credentials are unavailable"
                ) from None
            try:
                stored = await self._credential_resolver.resolve_credentials(
                    command.source_id,
                    command.expected_revision,
                    command.provider,
                )
            except RegisteredSourceCredentialsUnavailable:
                raise RegisteredSourceCheckUnavailable(
                    "registered source credentials are unavailable"
                ) from None
            if (
                stored is None
                or stored.source_id != command.source_id
                or stored.expected_revision != command.expected_revision
                or stored.provider is not command.provider
                or stored.authentication_mode is SourceCheckAuthenticationMode.KEEP
            ):
                raise RegisteredSourceCheckUnavailable(
                    "registered source credentials are unavailable"
                ) from None
            try:
                connection = replace(
                    stored,
                    endpoint=command.endpoint,
                    location=command.location,
                )
            except ValueError:
                raise RegisteredSourceCheckUnavailable(
                    "registered source credentials are unavailable"
                ) from None
        started_at_ns = self._monotonic_ns()
        result = await self._checker.check(connection, actor_id)
        elapsed_ns = max(0, self._monotonic_ns() - started_at_ns)
        result = replace(result, latency_ms=elapsed_ns / 1_000_000)
        if (
            self._probe_recorder is not None
            and command.authentication_mode is SourceCheckAuthenticationMode.KEEP
            and command.source_id is not None
            and command.expected_revision is not None
        ):
            try:
                await self._probe_recorder.record_registered_source_probe(
                    command, result
                )
            except Exception:
                raise RegisteredSourceCheckUnavailable(
                    "source check result could not be recorded"
                ) from None
        return result

    async def _resolve_reference(
        self, command: SourceConnectionInput
    ) -> SourceConnectionInput:
        resolver = self._credential_reference_resolver
        if resolver is None or command.credential_reference is None:
            raise RegisteredSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
        try:
            resolved = await resolver.resolve(
                command.provider, command.credential_reference
            )
        except Exception:
            # A deployment secret adapter may carry sensitive backend details.
            raise RegisteredSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
        if (
            not isinstance(resolved, ResolvedSourceCredentials)
            or resolved.provider is not command.provider
        ):
            raise RegisteredSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
        try:
            return replace(
                command,
                authentication_mode=SourceCheckAuthenticationMode.DIRECT,
                credential_reference=None,
                username=resolved.username,
                password=resolved.password,
                acl_token=resolved.acl_token,
            )
        except ValueError:
            raise RegisteredSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
