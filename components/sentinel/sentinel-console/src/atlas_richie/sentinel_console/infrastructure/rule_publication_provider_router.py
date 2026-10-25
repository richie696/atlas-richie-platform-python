"""Route publication operations only to explicitly configured providers."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from ..application.check_registered_source import SourceConnectionInput
from ..application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProvider,
    RulePublicationProviderRejected,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_publication_targets import RulePublicationTarget


class RulePublicationProviderRouter:
    """Select one exact adapter using the frozen target provider identity."""

    def __init__(
        self,
        adapters: Mapping[ConfigurationSourceProvider, RulePublicationProvider],
    ) -> None:
        configured = dict(adapters)
        if not configured:
            raise ValueError("publication provider adapters are invalid")
        for provider, adapter in configured.items():
            if not isinstance(provider, ConfigurationSourceProvider) or getattr(
                adapter, "supported_providers", None
            ) != frozenset({provider}):
                raise ValueError("publication provider adapters are invalid")
        self._adapters = MappingProxyType(configured)
        self.supported_providers = frozenset(configured)

    async def read_configuration(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> RuleConfigurationSnapshot:
        """Read from the adapter bound to this connection and target provider."""
        return await self._adapter(connection, target).read_configuration(
            connection, target
        )

    async def write_configuration_if_revision(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
        *,
        expected_revision: str | None,
        value: bytes,
    ) -> str:
        """CAS-write using only the exact provider-specific adapter."""
        return await self._adapter(connection, target).write_configuration_if_revision(
            connection,
            target,
            expected_revision=expected_revision,
            value=value,
        )

    def _adapter(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> RulePublicationProvider:
        if connection.provider is not target.provider:
            raise RulePublicationProviderRejected
        adapter = self._adapters.get(target.provider)
        if adapter is None:
            raise RulePublicationProviderRejected
        return adapter


__all__ = ["RulePublicationProviderRouter"]
