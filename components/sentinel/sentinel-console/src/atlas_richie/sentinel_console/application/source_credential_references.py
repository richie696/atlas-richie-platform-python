"""Deployment-owned resolution contract for opaque source credential refs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..domain.configuration_source import ConfigurationSourceProvider


@dataclass(frozen=True, slots=True)
class ResolvedSourceCredentials:
    """Ephemeral, provider-specific credentials returned by a deployment adapter."""

    provider: ConfigurationSourceProvider
    username: str | None = field(default=None, repr=False, compare=False)
    password: str | None = field(default=None, repr=False, compare=False)
    acl_token: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.provider is ConfigurationSourceProvider.NACOS:
            valid = bool(self.username and self.password) and self.acl_token is None
        else:
            valid = (
                bool(self.acl_token)
                and self.username is None
                and self.password is None
            )
        if not valid:
            raise ValueError("resolved credentials do not match source provider")


class SourceCredentialReferenceResolver(Protocol):
    """Resolve an opaque locator through the deployment's secret authority."""

    async def resolve(
        self,
        provider: ConfigurationSourceProvider,
        reference: str,
    ) -> ResolvedSourceCredentials | None:
        """Return ephemeral credentials, or None when the reference is unavailable."""
