"""Exact, provider-specific writable targets for rule publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from .configuration_source import ConfigurationSourceProvider
from .wire_strings import has_non_blank_wire_content, is_bounded_wire_text

_MAX_TARGET_IDENTIFIER_UNITS = 200
_MAX_TARGET_VALUE_UNITS = 512


def _valid_identity(value: object, maximum: int = _MAX_TARGET_VALUE_UNITS) -> bool:
    return (
        is_bounded_wire_text(value, maximum)
        and isinstance(value, str)
        and has_non_blank_wire_content(value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


@dataclass(frozen=True, slots=True)
class NacosRulePublicationTarget:
    """One exact Nacos namespace/group/dataId mapping resolved by the host."""

    binding_id: str
    source_id: str
    namespace: str
    group: str
    data_id: str

    @property
    def provider(self) -> ConfigurationSourceProvider:
        """Return the finite provider identity for this target."""
        return ConfigurationSourceProvider.NACOS

    def __post_init__(self) -> None:
        if (
            not _valid_identity(self.binding_id, _MAX_TARGET_IDENTIFIER_UNITS)
            or not _valid_identity(self.source_id, _MAX_TARGET_IDENTIFIER_UNITS)
            or not all(
                _valid_identity(value, _MAX_TARGET_VALUE_UNITS)
                for value in (self.namespace, self.group, self.data_id)
            )
        ):
            raise ValueError("Nacos rule publication target is invalid")


@dataclass(frozen=True, slots=True)
class ConsulRulePublicationTarget:
    """One exact Consul datacenter/key mapping resolved by the host."""

    binding_id: str
    source_id: str
    key: str
    datacenter: str | None = None

    @property
    def provider(self) -> ConfigurationSourceProvider:
        """Return the finite provider identity for this target."""
        return ConfigurationSourceProvider.CONSUL

    def __post_init__(self) -> None:
        if (
            not _valid_identity(self.binding_id, _MAX_TARGET_IDENTIFIER_UNITS)
            or not _valid_identity(self.source_id, _MAX_TARGET_IDENTIFIER_UNITS)
        ):
            raise ValueError("Consul rule publication identity is invalid")
        if not _valid_identity(self.key, _MAX_TARGET_VALUE_UNITS):
            raise ValueError("Consul rule publication key is invalid")
        if (
            self.key.startswith("/")
            or self.key.endswith("/")
            or "\\" in self.key
            or "?" in self.key
            or "#" in self.key
            or any(segment in {"", ".", ".."} for segment in self.key.split("/"))
        ):
            raise ValueError("Consul rule publication key is invalid")
        if self.datacenter is not None and (
            self.datacenter != ""
            and not _valid_identity(self.datacenter, _MAX_TARGET_VALUE_UNITS)
        ):
            raise ValueError("Consul rule publication datacenter is invalid")


RulePublicationTarget: TypeAlias = (
    NacosRulePublicationTarget | ConsulRulePublicationTarget
)


@dataclass(frozen=True, slots=True)
class VersionedRulePublicationTarget:
    """One exact binding target with frozen target and source revisions."""

    revision: str
    source_revision: str
    target: RulePublicationTarget

    def __post_init__(self) -> None:
        if not _valid_identity(self.revision, _MAX_TARGET_IDENTIFIER_UNITS):
            raise ValueError("rule publication target revision is invalid")
        if not _valid_identity(self.source_revision, _MAX_TARGET_IDENTIFIER_UNITS):
            raise ValueError("rule publication source revision is invalid")
        if not isinstance(
            self.target, (NacosRulePublicationTarget, ConsulRulePublicationTarget)
        ):
            raise ValueError("rule publication target is unsupported")
