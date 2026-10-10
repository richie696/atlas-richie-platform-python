"""Adapt the Console publication Port to exact Consul KV read/CAS primitives."""

from __future__ import annotations

from ..application.check_registered_source import SourceConnectionInput
from ..application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
    RulePublicationProviderRejected,
    RulePublicationProviderUnavailable,
)
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    RulePublicationTarget,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from .consul_rule_source_reader import (
    ConsulRuleSourceReadRejected,
    ConsulRuleSourceReadUnavailable,
    ConsulRuleSourceReader,
)
from .consul_rule_source_writer import (
    ConsulRuleSourceConflict,
    ConsulRuleSourceOutcomeUnknown,
    ConsulRuleSourceUnavailable,
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriteRejected,
    ConsulRuleSourceWriter,
)


class ConsulRulePublicationProvider:
    """Use frozen KV keys and ModifyIndex as the provider CAS revision."""

    supported_providers = frozenset({ConfigurationSourceProvider.CONSUL})

    def __init__(
        self,
        *,
        reader: ConsulRuleSourceReader,
        writer: ConsulRuleSourceWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read_configuration(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> RuleConfigurationSnapshot:
        consul_target = _consul_target(target)
        try:
            snapshot = await self._reader.read(connection, consul_target.key)
        except ConsulRuleSourceReadRejected:
            raise RulePublicationProviderRejected from None
        except ConsulRuleSourceReadUnavailable:
            raise RulePublicationProviderUnavailable from None
        return RuleConfigurationSnapshot(
            revision=snapshot.modify_index,
            value=snapshot.value,
        )

    async def write_configuration_if_revision(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
        *,
        expected_revision: str | None,
        value: bytes,
    ) -> str:
        consul_target = _consul_target(target)
        command = ConsulRuleSourceWrite(
            connection=connection,
            key=consul_target.key,
            expected_modify_index=expected_revision,
            value=value,
        )
        try:
            receipt = await self._writer.write(command)
        except ConsulRuleSourceConflict:
            raise RulePublicationProviderConflict from None
        except ConsulRuleSourceWriteRejected:
            raise RulePublicationProviderRejected from None
        except ConsulRuleSourceUnavailable:
            raise RulePublicationProviderUnavailable from None
        except ConsulRuleSourceOutcomeUnknown:
            raise RulePublicationProviderOutcomeUnknown from None
        return receipt.modify_index


def _consul_target(target: RulePublicationTarget) -> ConsulRulePublicationTarget:
    if not isinstance(target, ConsulRulePublicationTarget):
        raise ValueError("Consul provider received an unsupported target")
    return target


__all__ = ["ConsulRulePublicationProvider"]
