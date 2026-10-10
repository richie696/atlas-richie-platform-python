"""Explicit SQL + Consul composition for the durable publication worker."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
import ssl
from typing import Callable, Protocol, runtime_checkable

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
from ...infrastructure.consul_rule_publication_provider import (
    ConsulRulePublicationProvider,
)
from ...infrastructure.consul_rule_source_reader import ConsulRuleSourceReader
from ...infrastructure.consul_rule_source_writer import ConsulRuleSourceWriter
from ...infrastructure.nacos_rule_publication_provider import (
    NacosRulePublicationProvider,
)
from ...infrastructure.nacos_rule_source_reader import NacosRuleSourceReader
from ...infrastructure.nacos_rule_source_writer import NacosRuleSourceWriter
from ...infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
)
from ...infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)
from .rule_publication_reader import SqlAlchemyRulePublicationReader
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
    """Return an aware UTC instant; the worker normalizes it to wire precision."""
    return datetime.now(UTC)


def create_consul_rule_publication_worker(
    engine: _SqlConnectionEngine,
    *,
    target_policy: RegisteredSourceTargetPolicy,
    credential_resolver: RegisteredSourceCredentialResolver,
    credential_reference_resolver: SourceCredentialReferenceResolver | None,
    profile_id: str,
    ssl_context: ssl.SSLContext | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> RunRulePublicationWorker:
    """Build the Consul worker from deployment-owned security and SQL facts.

    This factory deliberately does not construct a database engine, choose DNS
    allowlists, resolve secrets, or enable its ASGI lifecycle. The caller owns
    those deployment decisions and must inject the returned worker into
    ``build_app`` explicitly.
    """
    if not isinstance(engine, _SqlConnectionEngine):
        raise ValueError("publication worker requires a SQL connection engine")
    if not isinstance(target_policy, RegisteredSourceTargetPolicy):
        raise ValueError("publication worker requires a registered-source policy")
    if not callable(clock):
        raise ValueError("publication worker clock is invalid")

    http_client = PinnedAioHttpJsonClient(ssl_context=ssl_context)
    provider = ConsulRulePublicationProvider(
        reader=ConsulRuleSourceReader(target_policy, http_client),
        writer=ConsulRuleSourceWriter(target_policy, http_client),
    )
    return RunRulePublicationWorker(
        outbox=SqlAlchemyRulePublishOutbox(engine),
        publication_reader=ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ),
        version_reader=ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)),
        source_connection_resolver=ResolveRegisteredSourceConnection(
            credential_resolver, credential_reference_resolver
        ),
        payload_encoder=SentinelRuleVersionJsonEncoder(profile_id),
        provider=provider,
        clock=clock,
    )


def create_nacos_rule_publication_worker(
    engine: _SqlConnectionEngine,
    *,
    target_policy: RegisteredSourceTargetPolicy,
    credential_resolver: RegisteredSourceCredentialResolver,
    credential_reference_resolver: SourceCredentialReferenceResolver | None,
    profile_id: str,
    ssl_context: ssl.SSLContext | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> RunRulePublicationWorker:
    """Build the Nacos worker with an explicit gRPC optional dependency.

    The deployment owns the SQL engine, hostname/IP and both HTTP/gRPC port
    grants. The writer never creates a config and requires an existing exact
    Nacos MD5 baseline before sending its gRPC CAS request.
    """
    if not isinstance(engine, _SqlConnectionEngine):
        raise ValueError("publication worker requires a SQL connection engine")
    if not isinstance(target_policy, RegisteredSourceTargetPolicy):
        raise ValueError("publication worker requires a registered-source policy")
    if not callable(clock):
        raise ValueError("publication worker clock is invalid")

    http_client = PinnedAioHttpJsonClient(ssl_context=ssl_context)
    reader = NacosRuleSourceReader(target_policy, http_client)
    provider = NacosRulePublicationProvider(
        reader=reader,
        writer=NacosRuleSourceWriter(
            target_policy,
            reader,
            http_client=http_client,
        ),
    )
    return RunRulePublicationWorker(
        outbox=SqlAlchemyRulePublishOutbox(engine),
        publication_reader=ReadRulePublication(
            SqlAlchemyRulePublicationReader(engine)
        ),
        version_reader=ReadRuleVersion(SqlAlchemyRuleVersionReader(engine)),
        source_connection_resolver=ResolveRegisteredSourceConnection(
            credential_resolver, credential_reference_resolver
        ),
        payload_encoder=SentinelRuleVersionJsonEncoder(profile_id),
        provider=provider,
        clock=clock,
    )


__all__ = [
    "create_consul_rule_publication_worker",
    "create_nacos_rule_publication_worker",
]
