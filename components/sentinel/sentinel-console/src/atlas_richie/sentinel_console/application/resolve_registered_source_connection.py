"""Resolve an exact persisted source revision into ephemeral connection facts."""

from __future__ import annotations

from dataclasses import replace

from ..domain.configuration_source import ConfigurationSourceProvider
from .check_registered_source import (
    RegisteredSourceCredentialResolver,
    RegisteredSourceCredentialsUnavailable,
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from .source_credential_references import (
    ResolvedSourceCredentials,
    SourceCredentialReferenceResolver,
)


class RegisteredSourceConnectionUnavailable(RuntimeError):
    """The exact registered source or its credentials cannot be resolved."""


class ResolveRegisteredSourceConnection:
    """Resolve only the frozen source revision needed by a trusted worker."""

    def __init__(
        self,
        credential_resolver: RegisteredSourceCredentialResolver,
        credential_reference_resolver: SourceCredentialReferenceResolver | None = None,
    ) -> None:
        self._credential_resolver = credential_resolver
        self._credential_reference_resolver = credential_reference_resolver

    async def execute(
        self,
        source_id: str,
        source_revision: str,
        provider: ConfigurationSourceProvider,
    ) -> SourceConnectionInput:
        """Return an ephemeral direct connection or fail closed without details."""
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or not isinstance(source_revision, str)
            or not source_revision.strip()
            or not isinstance(provider, ConfigurationSourceProvider)
        ):
            raise ValueError("registered source identity is invalid")

        try:
            connection = await self._credential_resolver.resolve_credentials(
                source_id, source_revision, provider
            )
        except RegisteredSourceCredentialsUnavailable:
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            ) from None

        if (
            not isinstance(connection, SourceConnectionInput)
            or connection.source_id != source_id
            or connection.expected_revision != source_revision
            or connection.provider is not provider
            or connection.authentication_mode is SourceCheckAuthenticationMode.KEEP
        ):
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            )

        if (
            connection.authentication_mode
            is not SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE
        ):
            return connection

        resolver = self._credential_reference_resolver
        if resolver is None or connection.credential_reference is None:
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            )
        try:
            credentials = await resolver.resolve(
                provider, connection.credential_reference
            )
        except Exception:
            # Deployment secret adapters may include sensitive backend details.
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            ) from None
        if (
            not isinstance(credentials, ResolvedSourceCredentials)
            or credentials.provider is not provider
        ):
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            )

        try:
            return replace(
                connection,
                authentication_mode=SourceCheckAuthenticationMode.DIRECT,
                credential_reference=None,
                username=credentials.username,
                password=credentials.password,
                acl_token=credentials.acl_token,
            )
        except ValueError:
            raise RegisteredSourceConnectionUnavailable(
                "registered source connection is unavailable"
            ) from None


__all__ = [
    "RegisteredSourceConnectionUnavailable",
    "ResolveRegisteredSourceConnection",
]
