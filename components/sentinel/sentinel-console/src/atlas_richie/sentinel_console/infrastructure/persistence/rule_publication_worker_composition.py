"""Explicit SQL + Consul composition for the durable publication worker."""

from __future__ import annotations

import ssl
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncConnection

from ...application.check_registered_source import RegisteredSourceCredentialResolver
from ...application.read_rule_publication import ReadRulePublication
from ...application.read_rule_version import ReadRuleVersion
from ...application.resolve_registered_source_connection import (
    ResolveRegisteredSourceConnection,
)
from ...application.run_rule_publication_worker import RunRulePublicationWorker
from ...application.source_credential_references import (
    SourceCredentialReferenceResolver,
)
from ...domain.configuration_source import ConfigurationSourceProvider
from ...domain.utc_time import current_utc_millisecond_instant
from ...infrastructure.consul_rule_publication_provider import (
    ConsulRulePublicationProvider,
)
from ...infrastructure.consul_rule_source_reader import ConsulRuleSourceReader
from ...infrastructure.consul_rule_source_writer import ConsulRuleSourceWriter
from ...infrastructure.nacos_grpc_transport import (
    NacosGrpcTlsCredentials,
    NacosGrpcTransport,
)
from ...infrastructure.nacos_rule_publication_provider import (
    NacosRulePublicationProvider,
)
from ...infrastructure.nacos_rule_source_reader import NacosRuleSourceReader
from ...infrastructure.nacos_rule_source_writer import NacosRuleSourceWriter
from ...infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
)
from ...infrastructure.rule_publication_provider_router import (
    RulePublicationProviderRouter,
)
from ...infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)
from .rule_publication_reader import SqlAlchemyRulePublicationReader
from .rule_publication_store import SqlAlchemyRulePublicationStore
from .rule_publish_outbox import SqlAlchemyRulePublishOutbox
from .rule_version_reader import SqlAlchemyRuleVersionReader


@runtime_checkable
class _SqlConnectionEngine(Protocol):
    """Minimal SQLAlchemy connection boundary consumed by worker stores."""

    def connect(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a read connection."""

    def begin(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Open a transaction."""


def _utc_now() -> datetime:
    """Return an aware UTC instant at the Console wire precision."""
    return current_utc_millisecond_instant()


def create_consul_rule_publication_worker(
    engine: _SqlConnectionEngine,
    *,
    target_policy: RegisteredSourceTargetPolicy,
    credential_resolver: RegisteredSourceCredentialResolver,
    credential_reference_resolver: SourceCredentialReferenceResolver | None,
    profile_id: str,
    managed_binding_ids: frozenset[str] = frozenset(),
    ssl_context: ssl.SSLContext | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> RunRulePublicationWorker:
    """Build the Consul worker from deployment-owned security and SQL facts.

    This factory deliberately does not construct a database engine, choose DNS
    allowlists, resolve secrets, or enable its ASGI lifecycle. The caller owns
    those deployment decisions and must inject the returned worker into
    ``build_app`` explicitly.
    """
    return create_rule_publication_worker(
        engine,
        target_policies={ConfigurationSourceProvider.CONSUL: target_policy},
        credential_resolver=credential_resolver,
        credential_reference_resolver=credential_reference_resolver,
        profile_id=profile_id,
        managed_binding_ids=managed_binding_ids,
        ssl_context=ssl_context,
        clock=clock,
    )


def create_nacos_rule_publication_worker(
    engine: _SqlConnectionEngine,
    *,
    target_policy: RegisteredSourceTargetPolicy,
    credential_resolver: RegisteredSourceCredentialResolver,
    credential_reference_resolver: SourceCredentialReferenceResolver | None,
    profile_id: str,
    managed_binding_ids: frozenset[str] = frozenset(),
    ssl_context: ssl.SSLContext | None = None,
    grpc_tls_credentials: NacosGrpcTlsCredentials | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> RunRulePublicationWorker:
    """Build the Nacos worker with an explicit gRPC optional dependency.

    The deployment owns the SQL engine, hostname/IP, both HTTP/gRPC port
    grants, HTTP SSL context, and optional gRPC TLS credentials. The writer
    never creates a config and requires an existing exact Nacos MD5 baseline
    before sending its gRPC CAS request.
    """
    return create_rule_publication_worker(
        engine,
        target_policies={ConfigurationSourceProvider.NACOS: target_policy},
        credential_resolver=credential_resolver,
        credential_reference_resolver=credential_reference_resolver,
        profile_id=profile_id,
        managed_binding_ids=managed_binding_ids,
        ssl_context=ssl_context,
        grpc_tls_credentials=grpc_tls_credentials,
        clock=clock,
    )


def create_rule_publication_worker(
    engine: _SqlConnectionEngine,
    *,
    target_policies: Mapping[ConfigurationSourceProvider, RegisteredSourceTargetPolicy],
    credential_resolver: RegisteredSourceCredentialResolver,
    credential_reference_resolver: SourceCredentialReferenceResolver | None,
    profile_id: str,
    managed_binding_ids: frozenset[str] = frozenset(),
    ssl_context: ssl.SSLContext | None = None,
    grpc_tls_credentials: NacosGrpcTlsCredentials | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> RunRulePublicationWorker:
    """Build one SQL worker over the explicitly enabled provider set.

    Each provider receives only its own network policy; the router and outbox
    filter preserve the frozen provider identity through publication execution.
    """
    if not isinstance(engine, _SqlConnectionEngine):
        raise TypeError("publication worker requires a SQL connection engine")
    if not isinstance(target_policies, Mapping) or not target_policies:
        raise ValueError("publication worker requires provider target policies")
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise ValueError("publication worker profile identity is invalid")
    if not isinstance(managed_binding_ids, frozenset) or any(
        not isinstance(binding_id, str) or not binding_id.strip()
        for binding_id in managed_binding_ids
    ):
        raise ValueError("managed publication bindings are invalid")
    if grpc_tls_credentials is not None and not isinstance(
        grpc_tls_credentials, NacosGrpcTlsCredentials
    ):
        raise TypeError("publication worker gRPC TLS credentials are invalid")
    if grpc_tls_credentials is not None and (
        ConfigurationSourceProvider.NACOS not in target_policies
    ):
        raise ValueError("Nacos gRPC TLS requires a Nacos publication adapter")
    if not callable(clock):
        raise TypeError("publication worker clock is invalid")

    adapters = {}
    for provider, target_policy in target_policies.items():
        if not isinstance(provider, ConfigurationSourceProvider):
            raise TypeError("publication provider identity is invalid")
        if not isinstance(target_policy, RegisteredSourceTargetPolicy):
            raise TypeError("publication worker requires registered-source policies")
        http_client = PinnedAioHttpJsonClient(ssl_context=ssl_context)
        if provider is ConfigurationSourceProvider.CONSUL:
            adapters[provider] = ConsulRulePublicationProvider(
                reader=ConsulRuleSourceReader(target_policy, http_client),
                writer=ConsulRuleSourceWriter(target_policy, http_client),
            )
        elif provider is ConfigurationSourceProvider.NACOS:
            reader = NacosRuleSourceReader(target_policy, http_client)
            adapters[provider] = NacosRulePublicationProvider(
                reader=reader,
                writer=NacosRuleSourceWriter(
                    target_policy,
                    reader,
                    http_client=http_client,
                    grpc_client=NacosGrpcTransport(grpc_tls_credentials),
                    grpc_tls_enabled=grpc_tls_credentials is not None,
                ),
            )
        else:
            raise ValueError("publication provider is not supported")

    return RunRulePublicationWorker(
        outbox=SqlAlchemyRulePublishOutbox(engine),
        publication_reader=ReadRulePublication(SqlAlchemyRulePublicationReader(engine)),
        version_reader=ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)),
        source_connection_resolver=ResolveRegisteredSourceConnection(
            credential_resolver, credential_reference_resolver
        ),
        payload_encoder=SentinelRuleVersionJsonEncoder(profile_id),
        payload_checksum_writer=SqlAlchemyRulePublicationStore(engine),
        provider=RulePublicationProviderRouter(adapters),
        managed_binding_ids=managed_binding_ids,
        clock=clock,
    )


__all__ = [
    "create_consul_rule_publication_worker",
    "create_nacos_rule_publication_worker",
    "create_rule_publication_worker",
]
