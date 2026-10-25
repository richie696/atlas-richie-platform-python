"""Adapt the Console publication Port to Nacos 3.x config CAS operations."""

from __future__ import annotations

from ..application.check_registered_source import SourceConnectionInput
from ..application.rule_publication_ports import (
    RuleConfigurationSnapshot,
    RulePublicationProviderConflict,
    RulePublicationProviderOutcomeUnknown,
    RulePublicationProviderRejected,
    RulePublicationProviderUnavailable,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_publication_targets import (
    NacosRulePublicationTarget,
    RulePublicationTarget,
)
from .nacos_rule_source_reader import (
    NacosRuleSourceAbsent,
    NacosRuleSourceReadRejected,
    NacosRuleSourceReadUnavailable,
    NacosRuleSourceReader,
)
from .nacos_rule_source_writer import (
    NacosRuleSourceConflict,
    NacosRuleSourceOutcomeUnknown,
    NacosRuleSourceUnavailable,
    NacosRuleSourceWrite,
    NacosRuleSourceWriteRejected,
    NacosRuleSourceWriter,
)


class NacosRulePublicationProvider:
    """Use exact namespace/group/dataId identity and provider MD5 CAS tokens."""

    supported_providers = frozenset({ConfigurationSourceProvider.NACOS})

    def __init__(
        self,
        *,
        reader: NacosRuleSourceReader,
        writer: NacosRuleSourceWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read_configuration(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> RuleConfigurationSnapshot:
        nacos_target = _nacos_target(target)
        try:
            snapshot = await self._reader.read(connection, nacos_target)
        except NacosRuleSourceAbsent:
            return RuleConfigurationSnapshot(revision=None, value=None)
        except NacosRuleSourceReadRejected:
            raise RulePublicationProviderRejected from None
        except NacosRuleSourceReadUnavailable:
            raise RulePublicationProviderUnavailable from None
        return RuleConfigurationSnapshot(
            revision=snapshot.md5,
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
        nacos_target = _nacos_target(target)
        command = NacosRuleSourceWrite(
            connection=connection,
            target=nacos_target,
            expected_md5=expected_revision,
            value=value,
        )
        try:
            receipt = await self._writer.write(command)
        except NacosRuleSourceConflict:
            raise RulePublicationProviderConflict from None
        except NacosRuleSourceWriteRejected:
            raise RulePublicationProviderRejected from None
        except NacosRuleSourceUnavailable:
            raise RulePublicationProviderUnavailable from None
        except NacosRuleSourceOutcomeUnknown:
            raise RulePublicationProviderOutcomeUnknown from None
        return receipt.md5


def _nacos_target(target: RulePublicationTarget) -> NacosRulePublicationTarget:
    if not isinstance(target, NacosRulePublicationTarget):
        raise ValueError("Nacos provider received an unsupported target")
    return target


__all__ = ["NacosRulePublicationProvider"]
