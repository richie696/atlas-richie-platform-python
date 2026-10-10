"""Application contract for a read-only first-run configuration-source check."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol, TypeAlias

from ..domain.configuration_source import ConfigurationSourceProvider
from .source_credential_references import (
    ResolvedSourceCredentials,
    SourceCredentialReferenceResolver,
)


class BootstrapSourceProvider(StrEnum):
    """Supported configuration-source products."""

    NACOS = "nacos"
    CONSUL = "consul"


class BootstrapSourceFailureReason(StrEnum):
    """Finite source-check failures safe to disclose to the operator."""

    AUTHENTICATION = "authentication"
    CONNECTION = "connection"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class NoSourceAuthentication:
    """An explicitly unauthenticated source configuration."""


@dataclass(frozen=True, slots=True)
class SourceCredentialReference:
    """Opaque deployment-owned credential locator; never resolved by the UI."""

    reference: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class NacosDirectCredentials:
    """Ephemeral Nacos credentials supplied by an operator."""

    username: str = field(repr=False, compare=False)
    password: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ConsulDirectCredentials:
    """Ephemeral Consul ACL token supplied by an operator."""

    acl_token: str = field(repr=False, compare=False)


SourceAuthentication: TypeAlias = (
    NoSourceAuthentication
    | SourceCredentialReference
    | NacosDirectCredentials
    | ConsulDirectCredentials
)


@dataclass(frozen=True, slots=True)
class BootstrapSourceCandidate:
    """Provider-specific endpoint and location with ephemeral authentication."""

    provider: BootstrapSourceProvider
    endpoint: str
    location: str
    authentication: SourceAuthentication

    def __post_init__(self) -> None:
        valid_authentication = (
            isinstance(
                self.authentication,
                (NoSourceAuthentication, SourceCredentialReference),
            )
            or (
                self.provider is BootstrapSourceProvider.NACOS
                and isinstance(self.authentication, NacosDirectCredentials)
            )
            or (
                self.provider is BootstrapSourceProvider.CONSUL
                and isinstance(self.authentication, ConsulDirectCredentials)
            )
        )
        if not valid_authentication:
            raise ValueError("source authentication does not match its provider")


@dataclass(frozen=True, slots=True)
class BootstrapSourceCheckResult:
    """Read-only reachability fact and an optional finite failure reason."""

    reachable: bool
    reason: BootstrapSourceFailureReason | None = None

    def __post_init__(self) -> None:
        if self.reachable == (self.reason is not None):
            raise ValueError("reachability and failure reason are inconsistent")


class BootstrapSourceCheckUnavailable(RuntimeError):
    """The configured source checker cannot produce a reliable result."""


class BootstrapSourceChecker(Protocol):
    """Check access without registration, rule writes, or secret persistence."""

    async def check(
        self, candidate: BootstrapSourceCandidate
    ) -> BootstrapSourceCheckResult:
        """Return a bounded connectivity fact or raise on checker unavailability."""


class CheckBootstrapSource:
    """Resolve a deployment reference before checking a first-run source."""

    def __init__(
        self,
        checker: BootstrapSourceChecker,
        credential_reference_resolver: SourceCredentialReferenceResolver | None,
    ) -> None:
        self._checker = checker
        self._credential_reference_resolver = credential_reference_resolver

    async def execute(
        self, candidate: BootstrapSourceCandidate
    ) -> BootstrapSourceCheckResult:
        """Probe with resolved ephemeral credentials or fail closed."""
        if isinstance(candidate.authentication, SourceCredentialReference):
            candidate = await self._resolve_reference(candidate)
        return await self._checker.check(candidate)

    async def _resolve_reference(
        self, candidate: BootstrapSourceCandidate
    ) -> BootstrapSourceCandidate:
        resolver = self._credential_reference_resolver
        authentication = candidate.authentication
        if resolver is None or not isinstance(authentication, SourceCredentialReference):
            raise BootstrapSourceCheckUnavailable("source credentials are unavailable")
        try:
            resolved = await resolver.resolve(
                ConfigurationSourceProvider(candidate.provider.value),
                authentication.reference,
            )
        except Exception:
            raise BootstrapSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
        if (
            not isinstance(resolved, ResolvedSourceCredentials)
            or resolved.provider.value != candidate.provider.value
        ):
            raise BootstrapSourceCheckUnavailable("source credentials are unavailable")
        direct_authentication: NacosDirectCredentials | ConsulDirectCredentials
        if candidate.provider is BootstrapSourceProvider.NACOS:
            if resolved.username is None or resolved.password is None:
                raise BootstrapSourceCheckUnavailable(
                    "source credentials are unavailable"
                ) from None
            direct_authentication = NacosDirectCredentials(
                resolved.username, resolved.password
            )
        else:
            if resolved.acl_token is None:
                raise BootstrapSourceCheckUnavailable(
                    "source credentials are unavailable"
                ) from None
            direct_authentication = ConsulDirectCredentials(resolved.acl_token)
        try:
            return replace(candidate, authentication=direct_authentication)
        except ValueError:
            raise BootstrapSourceCheckUnavailable(
                "source credentials are unavailable"
            ) from None
