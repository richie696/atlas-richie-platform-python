"""Read one binding's exact authoritative rules from a registered config source."""

from __future__ import annotations

import hashlib
import json
import ssl
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from atlas_richie.contracts.rules.managed_publication.v1.managed_publication import (
    decode_managed_rule_publication,
)

from ..application.check_registered_source import SourceConnectionInput
from ..application.resolve_registered_source_connection import (
    RegisteredSourceConnectionUnavailable,
    ResolveRegisteredSourceConnection,
)
from ..application.rule_binding_ports import RuleBindingAuthorityUnavailable
from ..application.rule_publication_ports import RulePublicationAuthorityUnavailable
from ..application.rule_snapshot_ports import (
    RuleSetSnapshotAuthorityUnavailable,
    RuleSetSnapshotInvalid,
    RuleSetSnapshotNotFound,
    RuleSetSnapshotReader,
    RuleSetSnapshotTargetMissing,
    RuleSetSnapshotUnsupportedProfile,
)
from ..domain.configuration_source import ConfigurationSourceProvider
from ..domain.rule_bindings import RuleBinding
from ..domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
    RulePublicationTarget,
    VersionedRulePublicationTarget,
)
from ..domain.rule_snapshots import RuleRecord, RuleSetSnapshot
from ..domain.utc_time import current_utc_millisecond_instant
from .consul_rule_source_reader import (
    ConsulRuleSourceReader,
    ConsulRuleSourceReadRejected,
    ConsulRuleSourceReadUnavailable,
)
from .nacos_rule_source_reader import (
    NacosRuleSourceAbsent,
    NacosRuleSourceReader,
    NacosRuleSourceReadRejected,
    NacosRuleSourceReadUnavailable,
)
from .registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
)
from .rule_catalog_profile_adapters import (
    UnsupportedRuleCatalogCapability,
    parse_rule_catalog_values,
)
from .rule_profile_capabilities import (
    SUPPORTED_RULE_CATALOG_CAPABILITIES,
    SUPPORTED_RULE_CATALOG_PROFILES,
)

_EMPTY_RULE_ARRAY = b"[]"


class RuleBindingReader(Protocol):
    """Read exact Console binding metadata needed for a source snapshot."""

    async def read_rule_binding(self, binding_id: str) -> RuleBinding | None:
        """Return the exact binding or no row."""


class RulePublicationTargetReader(Protocol):
    """Read a binding's immutable provider target and source revision."""

    async def read_rule_publication_target(
        self, binding_id: str
    ) -> VersionedRulePublicationTarget | None:
        """Return the exact versioned provider target or no row."""


class RuleSourceSnapshotAdapter(Protocol):
    """Translate a provider's exact read into bytes and its opaque revision."""

    async def read(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> tuple[bytes | None, str | None]:
        """Return raw configuration bytes and the provider-owned revision."""


class ConsulRuleSetSnapshotAdapter:
    """Adapt exact Consul KV GET snapshots to the rule-read boundary."""

    def __init__(self, reader: ConsulRuleSourceReader) -> None:
        self._reader = reader

    async def read(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> tuple[bytes | None, str | None]:
        if not isinstance(target, ConsulRulePublicationTarget):
            raise RuleSetSnapshotAuthorityUnavailable
        try:
            snapshot = await self._reader.read(connection, target.key)
        except ConsulRuleSourceReadRejected:
            raise RuleSetSnapshotAuthorityUnavailable from None
        except ConsulRuleSourceReadUnavailable:
            raise RuleSetSnapshotAuthorityUnavailable from None
        if snapshot.value is None:
            raise RuleSetSnapshotTargetMissing
        return snapshot.value, snapshot.modify_index


class NacosRuleSetSnapshotAdapter:
    """Adapt exact Nacos 3 config reads to the rule-read boundary."""

    def __init__(self, reader: NacosRuleSourceReader) -> None:
        self._reader = reader

    async def read(
        self,
        connection: SourceConnectionInput,
        target: RulePublicationTarget,
    ) -> tuple[bytes | None, str | None]:
        if not isinstance(target, NacosRulePublicationTarget):
            raise RuleSetSnapshotAuthorityUnavailable
        try:
            snapshot = await self._reader.read(connection, target)
        except NacosRuleSourceAbsent:
            raise RuleSetSnapshotTargetMissing from None
        except NacosRuleSourceReadRejected:
            raise RuleSetSnapshotAuthorityUnavailable from None
        except NacosRuleSourceReadUnavailable:
            raise RuleSetSnapshotAuthorityUnavailable from None
        return snapshot.value, snapshot.md5


class RegisteredRuleSetSnapshotReader(RuleSetSnapshotReader):
    """Resolve exact SQL authorities, fetch one source value, and decode it."""

    def __init__(
        self,
        *,
        binding_reader: RuleBindingReader,
        target_reader: RulePublicationTargetReader,
        connection_resolver: ResolveRegisteredSourceConnection,
        provider_adapters: Mapping[
            ConfigurationSourceProvider, RuleSourceSnapshotAdapter
        ],
        clock: Callable[[], datetime] = current_utc_millisecond_instant,
    ) -> None:
        if not provider_adapters or any(
            not isinstance(provider, ConfigurationSourceProvider)
            for provider in provider_adapters
        ):
            raise ValueError("rule snapshot provider adapters are invalid")
        if not callable(clock):
            raise TypeError("rule snapshot clock is invalid")
        self._binding_reader = binding_reader
        self._target_reader = target_reader
        self._connection_resolver = connection_resolver
        self._provider_adapters = dict(provider_adapters)
        self._clock = clock

    async def read_rule_set_snapshot(self, binding_id: str) -> RuleSetSnapshot:
        """Return only the snapshot whose SQL metadata and provider target agree."""
        try:
            binding = await self._binding_reader.read_rule_binding(binding_id)
            if binding is None:
                raise RuleSetSnapshotNotFound
            if (
                binding.profile not in SUPPORTED_RULE_CATALOG_PROFILES
                or binding.kind.value
                not in SUPPORTED_RULE_CATALOG_CAPABILITIES.get(binding.profile, ())
            ):
                raise RuleSetSnapshotUnsupportedProfile
            versioned_target = await self._target_reader.read_rule_publication_target(
                binding_id
            )
            if versioned_target is None:
                raise RuleSetSnapshotAuthorityUnavailable
            target = versioned_target.target
            if (
                target.binding_id != binding.id
                or target.source_id != binding.source_id
                or target.provider not in self._provider_adapters
            ):
                raise RuleSetSnapshotAuthorityUnavailable
            connection = await self._connection_resolver.execute(
                target.source_id,
                versioned_target.source_revision,
                target.provider,
            )
            value, source_revision = await self._provider_adapters[
                target.provider
            ].read(connection, target)
            if (value is None) != (source_revision is None):
                raise RuleSetSnapshotAuthorityUnavailable
            if value is None:
                raise RuleSetSnapshotTargetMissing
            return _snapshot_from_value(
                binding,
                value,
                source_revision,
                clock=self._clock,
            )
        except RuleSetSnapshotNotFound:
            raise
        except RuleSetSnapshotAuthorityUnavailable:
            raise
        except RegisteredSourceConnectionUnavailable:
            raise RuleSetSnapshotAuthorityUnavailable from None
        except (
            RuleBindingAuthorityUnavailable,
            RulePublicationAuthorityUnavailable,
        ):
            raise RuleSetSnapshotAuthorityUnavailable from None


def create_registered_source_rule_set_snapshot_reader(
    *,
    binding_reader: RuleBindingReader,
    target_reader: RulePublicationTargetReader,
    connection_resolver: ResolveRegisteredSourceConnection,
    target_policies: Mapping[ConfigurationSourceProvider, RegisteredSourceTargetPolicy],
    ssl_context: ssl.SSLContext | None = None,
    clock: Callable[[], datetime] = current_utc_millisecond_instant,
) -> RegisteredRuleSetSnapshotReader:
    """Build source adapters only for explicitly authorized provider policies."""
    adapters: dict[ConfigurationSourceProvider, RuleSourceSnapshotAdapter] = {}
    http_client = PinnedAioHttpJsonClient(ssl_context=ssl_context)
    for provider, policy in target_policies.items():
        if not isinstance(policy, RegisteredSourceTargetPolicy):
            raise TypeError("rule snapshot target policy is invalid")
        if provider is ConfigurationSourceProvider.CONSUL:
            adapters[provider] = ConsulRuleSetSnapshotAdapter(
                ConsulRuleSourceReader(policy, http_client)
            )
        elif provider is ConfigurationSourceProvider.NACOS:
            adapters[provider] = NacosRuleSetSnapshotAdapter(
                NacosRuleSourceReader(policy, http_client)
            )
        else:
            raise ValueError("rule snapshot provider is unsupported")
    return RegisteredRuleSetSnapshotReader(
        binding_reader=binding_reader,
        target_reader=target_reader,
        connection_resolver=connection_resolver,
        provider_adapters=adapters,
        clock=clock,
    )


def _snapshot_from_value(
    binding: RuleBinding,
    value: bytes | None,
    source_revision: str | None,
    *,
    clock: Callable[[], datetime],
) -> RuleSetSnapshot:
    raw_value = _EMPTY_RULE_ARRAY if value is None else value
    version_id = None
    if value is not None and _looks_like_managed_envelope(value):
        try:
            envelope = decode_managed_rule_publication(value)
        except (TypeError, ValueError):
            raise RuleSetSnapshotInvalid from None
        if (
            envelope.binding_id != binding.id
            or envelope.rule_kind.value != binding.kind.value
            or envelope.profile_id != binding.profile
        ):
            raise RuleSetSnapshotInvalid
        raw_value = envelope.rule_payload
        version_id = envelope.target_version_id
    try:
        decoded = json.loads(
            raw_value.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
            parse_float=(
                Decimal
                if binding.profile
                in {"sentinel-java-v1", "sentinel-go-v1", "sentinel-rust-v1"}
                else float
            ),
        )
        parsed_rules = parse_rule_catalog_values(binding.profile, binding.kind, decoded)
        records = tuple(
            RuleRecord(
                id=_source_record_id(index, raw_rule),
                rule=parsed_rules[index],
            )
            for index, raw_rule in enumerate(decoded)
        )
        return RuleSetSnapshot(
            binding=binding,
            version_id=version_id,
            checksum=f"sha256:{hashlib.sha256(raw_value).hexdigest()}",
            source_revision=source_revision,
            as_of=clock(),
            records=records,
        )
    except RuleSetSnapshotAuthorityUnavailable:
        raise
    except UnsupportedRuleCatalogCapability:
        raise RuleSetSnapshotUnsupportedProfile from None
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RuleSetSnapshotInvalid from None


def _looks_like_managed_envelope(value: bytes) -> bool:
    """Recognize object-shaped Console-managed values without leaking bytes."""
    try:
        decoded = json.loads(value.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(decoded, dict)


def _source_record_id(index: int, value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: (
            str(item) if isinstance(item, Decimal) else _raise_json_type(item)
        ),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()[:24]
    return f"source-{index + 1}-{digest}"


def _raise_json_type(value: object) -> object:
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON fields are not allowed")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise ValueError("non-JSON numeric constants are not allowed")


__all__ = [
    "ConsulRuleSetSnapshotAdapter",
    "NacosRuleSetSnapshotAdapter",
    "RegisteredRuleSetSnapshotReader",
    "create_registered_source_rule_set_snapshot_reader",
]
