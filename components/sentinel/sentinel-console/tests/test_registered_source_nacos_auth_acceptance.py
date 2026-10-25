"""Opt-in authentication acceptance against isolated Nacos 3.2.4 over TLS."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from aiohttp import ClientSession, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.api.rule_candidate_parsing import (
    parse_rule_candidate,
)
from atlas_richie.sentinel_console.api.rule_snapshot_serializers import rule_record_body
from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.mutate_registered_source import (
    RegisteredSourceMutation,
    SourceMutationKind,
    SourceMutationStatus,
)
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    CreateRuleActivationPlan,
    PublishRuleVersion,
    RuleMutationCommand,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.application.resolve_registered_source_connection import (
    ResolveRegisteredSourceConnection,
)
from atlas_richie.sentinel_console.application.run_rule_activation_plan_worker import (
    RuleActivationPlanWorkerOutcome,
    RunRuleActivationPlanWorker,
)
from atlas_richie.sentinel_console.application.run_rule_publication_worker import (
    RulePublicationWorkerOutcome,
)
from atlas_richie.sentinel_console.application.source_credential_references import (
    ResolvedSourceCredentials,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleBinding, RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import (
    candidate_checksum,
)
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    NacosRulePublicationTarget,
    VersionedRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcOutcomeUnknown,
    NacosGrpcTlsCredentials,
    NacosGrpcTransport,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceConflict,
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
    NacosRuleSourceWriteRejected,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
    SqlAlchemyRegisteredSourceStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_reader import (
    SqlAlchemyRuleActivationPlanReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_activation_plan_work_queue import (
    SqlAlchemyRuleActivationPlanWorkQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_store import (
    SqlAlchemyRuleMutationStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_worker_composition import (
    create_nacos_rule_publication_worker,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker_composition import (
    compose_provider_registered_source_checker,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_RUN_ACCEPTANCE = os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE") == "1"
_RUN_INSTALLED_CLI_ACCEPTANCE = (
    os.environ.get("SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_AUTH_ACCEPTANCE") == "1"
)
_RUN_INSTALLED_CLI_POSTGRES_ACCEPTANCE = (
    os.environ.get("SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_POSTGRES_AUTH_ACCEPTANCE")
    == "1"
)
_NACOS_IMAGE = "nacos/nacos-server:v3.2.4"
_ADMIN_PASSWORD = "Isolated-nacos-admin-password-2026"
_TOKEN_SECRET = "VGhpc0lzTXlDb21tdW5pdHlUZXN0VG9rZW5TZWNyZXRLZXlTdHJpbmc="
_TLS_HOSTNAME = "nacos-auth.test"
_MYSQL_DATABASE_URL = os.environ.get("SENTINEL_CONSOLE_TEST_MYSQL_URL")
_POSTGRES_DATABASE_URL = os.environ.get("SENTINEL_CONSOLE_TEST_POSTGRES_URL")
if _MYSQL_DATABASE_URL is not None and _POSTGRES_DATABASE_URL is not None:
    raise ValueError("select exactly one disposable SQL dialect for this acceptance")
if _MYSQL_DATABASE_URL is not None:
    _mysql_url = make_url(_MYSQL_DATABASE_URL)
    if (
        _mysql_url.drivername != "mysql+asyncmy"
        or not _mysql_url.database
        or not _mysql_url.database.startswith("sentinel_console_test_")
        or _mysql_url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "SENTINEL_CONSOLE_TEST_MYSQL_URL must target the disposable loopback MySQL database"
        )
if _POSTGRES_DATABASE_URL is not None:
    _postgres_url = make_url(_POSTGRES_DATABASE_URL)
    if (
        _postgres_url.drivername != "postgresql+psycopg"
        or not _postgres_url.database
        or not _postgres_url.database.startswith("sentinel_console_test_")
        or _postgres_url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError(
            "SENTINEL_CONSOLE_TEST_POSTGRES_URL must target the disposable loopback PostgreSQL database"
        )


@unittest.skipUnless(
    _RUN_ACCEPTANCE,
    "set SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE=1 to start disposable Nacos",
)
class NacosRegisteredSourceAuthAcceptance(unittest.IsolatedAsyncioTestCase):
    """Verify real Nacos credentials through an HTTPS trust boundary."""

    async def asyncSetUp(self) -> None:
        self.container_name = f"sentinel-nacos-auth-{uuid4().hex[:12]}"
        self._started = False
        self._proxy_runner: web.AppRunner | None = None
        self._grpc_proxy_server: asyncio.Server | None = None
        self._grpc_proxy_tasks: set[asyncio.Task[None]] = set()
        self._certificate_directory = None
        try:
            self._http_port, self._grpc_port = _available_nacos_port_pair()
            await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    self.container_name,
                    "--env",
                    "MODE=standalone",
                    "--env",
                    "NACOS_AUTH_ENABLE=true",
                    "--env",
                    "NACOS_AUTH_ADMIN_ENABLE=true",
                    "--env",
                    "NACOS_AUTH_CONSOLE_ENABLE=true",
                    "--env",
                    "NACOS_AUTH_SYSTEM_TYPE=nacos",
                    "--env",
                    f"NACOS_AUTH_TOKEN={_TOKEN_SECRET}",
                    "--env",
                    "NACOS_AUTH_IDENTITY_KEY=sentinel-local-test",
                    "--env",
                    "NACOS_AUTH_IDENTITY_VALUE=sentinel-local-test-only",
                    "--publish",
                    f"127.0.0.1:{self._http_port}:8848/tcp",
                    "--publish",
                    f"127.0.0.1:{self._grpc_port}:9848/tcp",
                    _NACOS_IMAGE,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._started = True
            self.nacos_endpoint = f"http://127.0.0.1:{self._http_port}/nacos"
            await asyncio.to_thread(self._initialize_admin)
            await self._start_tls_proxy()
        except BaseException:
            await self._stop_tls_proxy()
            self._remove_container()
            raise

    async def asyncTearDown(self) -> None:
        await self._stop_tls_proxy()
        self._remove_container()

    async def test_direct_credentials_authenticate_and_bad_password_is_rejected(
        self,
    ) -> None:
        port = int(self.endpoint.rsplit(":", 1)[1].split("/", 1)[0])
        rules = (
            RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.NACOS,
                _TLS_HOSTNAME,
                ("127.0.0.1/32",),
                frozenset({port}),
            ),
        )
        checker = compose_provider_registered_source_checker(
            rules,
            ssl_context=self._client_ssl_context,
            resolver=_LoopbackResolverWithPort(port),
        )
        valid = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password=_ADMIN_PASSWORD,
        )
        invalid = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password="incorrect-password",
        )

        accepted = await checker.check(valid, "acceptance-operator")
        denied = await checker.check(invalid, "acceptance-operator")

        self.assertTrue(accepted.reachable, accepted.reason)
        self.assertEqual(accepted.capabilities, (SourceCheckCapability.READ,))
        self.assertIsNone(accepted.reason)
        self.assertFalse(denied.reachable)
        self.assertEqual(denied.reason, SourceCheckFailureReason.AUTHENTICATION)
        self.assertEqual(denied.capabilities, ())
        self.assertNotIn(_ADMIN_PASSWORD, repr(accepted))
        self.assertNotIn("incorrect-password", repr(denied))

    @unittest.skipUnless(
        _RUN_INSTALLED_CLI_ACCEPTANCE,
        "set SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_AUTH_ACCEPTANCE=1 to verify the installed CLI",
    )
    async def test_installed_cli_bootstrap_uses_authenticated_nacos_over_verified_tls(
        self,
    ) -> None:
        database_url = os.environ.get("SENTINEL_CONSOLE_TEST_MYSQL_URL")
        if not database_url:
            self.skipTest(
                "run through with_disposable_e2e_dependencies.sh for isolated MySQL"
            )
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        await asyncio.to_thread(
            self._run_installed_cli_nacos_auth_acceptance,
            database_url,
            "mysql",
        )

    @unittest.skipUnless(
        _RUN_INSTALLED_CLI_POSTGRES_ACCEPTANCE,
        "set SENTINEL_CONSOLE_RUN_INSTALLED_NACOS_POSTGRES_AUTH_ACCEPTANCE=1 to verify PostgreSQL",
    )
    async def test_installed_cli_postgresql_bootstrap_uses_authenticated_nacos_over_verified_tls(
        self,
    ) -> None:
        database_url = os.environ.get("SENTINEL_CONSOLE_TEST_POSTGRES_URL")
        if not database_url:
            self.skipTest(
                "run through with_disposable_postgresql_acceptance.sh for isolated PostgreSQL"
            )
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        await asyncio.to_thread(
            self._run_installed_cli_nacos_auth_acceptance,
            database_url,
            "postgresql",
        )

    def _run_installed_cli_nacos_auth_acceptance(
        self, database_url: str, database_kind: str
    ) -> None:
        source_port = self._proxy_port
        endpoint = f"https://127.0.0.1:{source_port}/nacos"
        certificate_path = Path(self._certificate_directory.name) / "certificate.pem"
        source_password = _ADMIN_PASSWORD
        from test_installed_cli_bootstrap_acceptance import (
            InstalledCliBootstrapAcceptanceTests,
        )

        acceptance = InstalledCliBootstrapAcceptanceTests()

        def verify_installed_console() -> None:
            acceptance._run_installed_cli_acceptance(
                database_url,
                database_kind,
                after_initialize=lambda port, runtime_directory, service_environment: (
                    acceptance._assert_installed_live_nacos_probe(
                        port,
                        runtime_directory,
                        service_environment,
                        endpoint=endpoint,
                        password=source_password,
                    )
                ),
                restart_before_callback=True,
                initial_source={
                    "provider": "nacos",
                    "endpoint": endpoint,
                    "namespace": "public",
                    "authentication": {
                        "mode": "direct",
                        "username": "nacos",
                        "password": source_password,
                    },
                },
                service_environment_overrides={
                    "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": (
                        f"nacos|127.0.0.1|127.0.0.1/32|{source_port}"
                    ),
                    "SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE": str(
                        certificate_path
                    ),
                },
                expected_source_secret=source_password,
            )

        verify_installed_console()

    async def test_authenticated_create_only_write_is_read_back_and_never_overwrites(
        self,
    ) -> None:
        port = int(self.endpoint.rsplit(":", 1)[1].split("/", 1)[0])
        target_policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    _TLS_HOSTNAME,
                    ("127.0.0.1/32",),
                    frozenset({port}),
                ),
            ),
            resolver=_LoopbackResolverWithPort(port),
        )
        http_client = PinnedAioHttpJsonClient(ssl_context=self._client_ssl_context)
        reader = NacosRuleSourceReader(target_policy, http_client)
        writer = NacosRuleSourceWriter(target_policy, reader, http_client=http_client)
        source_id = f"nacos-auth-{uuid4().hex}"
        data_id = f"sentinel-auth-{uuid4().hex}.json"
        connection = SourceConnectionInput(
            source_id=source_id,
            expected_revision="disposable-auth-source-revision",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password=_ADMIN_PASSWORD,
        )
        target = NacosRulePublicationTarget(
            binding_id=f"binding-{uuid4().hex}",
            source_id=source_id,
            namespace="public",
            group="SENTINEL_AUTH_ACCEPTANCE",
            data_id=data_id,
        )
        candidate = b'{"version":"authenticated-create-only"}'
        receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=None,
                value=candidate,
            )
        )

        snapshot = await reader.read(connection, target)
        self.assertEqual(snapshot.value, candidate)
        self.assertEqual(snapshot.md5, receipt.md5)
        self.assertNotIn(_ADMIN_PASSWORD, repr(connection))
        self.assertNotIn(_ADMIN_PASSWORD, repr(snapshot))

        with self.assertRaises(NacosRuleSourceConflict):
            await writer.write(
                NacosRuleSourceWrite(
                    connection=connection,
                    target=target,
                    expected_md5=None,
                    value=b'{"version":"must-not-overwrite"}',
                )
            )

        invalid_connection = SourceConnectionInput(
            source_id=source_id,
            expected_revision="disposable-auth-source-revision",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password="incorrect-password",
        )
        with self.assertRaises(NacosRuleSourceWriteRejected):
            await writer.write(
                NacosRuleSourceWrite(
                    connection=invalid_connection,
                    target=target,
                    expected_md5=None,
                    value=b'{"version":"must-not-write"}',
                )
            )

        final_snapshot = await reader.read(connection, target)
        self.assertEqual(final_snapshot.value, candidate)
        self.assertEqual(final_snapshot.md5, receipt.md5)

    async def test_authenticated_rule_catalog_reads_updates_and_preserves_lkg(
        self,
    ) -> None:
        """Read Nacos rules through SQL authority without a Runtime request."""
        from atlas_richie.contracts.rules.managed_publication.v1.managed_publication import (
            ManagedRuleKind,
            ManagedRulePublicationV1,
            encode_managed_rule_publication,
        )
        from atlas_richie.sentinel_console.application.refresh_rule_catalog import (
            RefreshRuleCatalog,
        )
        from atlas_richie.sentinel_console.domain.rule_catalog import RuleCatalogQuery
        from atlas_richie.sentinel_console.infrastructure.persistence.models import (
            RuleBindingRecord,
            RulePublicationTargetRecord,
        )
        from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
            encrypt_registered_source_credentials,
        )
        from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
            SqlAlchemyRuleBindingDirectoryReader,
        )
        from atlas_richie.sentinel_console.infrastructure.persistence.rule_catalog_projection import (
            SqlAlchemyRuleCatalogProjection,
        )
        from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
            target_body,
            target_location,
        )
        from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_reader import (
            SqlAlchemyRulePublicationTargetReader,
        )
        from atlas_richie.sentinel_console.infrastructure.rule_set_snapshot_reader import (
            create_registered_source_rule_set_snapshot_reader,
        )

        instant = datetime.now(UTC)
        now = instant.replace(microsecond=(instant.microsecond // 1_000) * 1_000)
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        owner_id = f"nacos-catalog-owner-{uuid4().hex}"
        owner_name = f"nacos-catalog-owner-{uuid4().hex}"
        source_id = f"nacos-catalog-source-{uuid4().hex}"
        source_revision = f"nacos-catalog-source-revision-{uuid4().hex}"
        binding_id = f"nacos-catalog-binding-{uuid4().hex}"
        managed_binding_id = f"nacos-managed-catalog-binding-{uuid4().hex}"
        target = NacosRulePublicationTarget(
            binding_id=binding_id,
            source_id=source_id,
            namespace="public",
            group="SENTINEL_RULE_CATALOG_ACCEPTANCE",
            data_id=f"sentinel-rule-catalog-{uuid4().hex}.json",
        )
        managed_target = NacosRulePublicationTarget(
            binding_id=managed_binding_id,
            source_id=source_id,
            namespace="public",
            group="SENTINEL_RULE_CATALOG_ACCEPTANCE",
            data_id=f"sentinel-managed-rule-catalog-{uuid4().hex}.json",
        )
        connection = SourceConnectionInput(
            source_id=source_id,
            expected_revision=source_revision,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password=_ADMIN_PASSWORD,
        )
        cipher = AesGcmSecretCipher("nacos-catalog-v1", {"nacos-catalog-v1": b"c" * 32})
        encrypted = encrypt_registered_source_credentials(connection, source_id, cipher)
        assert encrypted is not None
        port = self._proxy_port
        policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    _TLS_HOSTNAME,
                    ("127.0.0.1/32",),
                    frozenset({port, port + 1_000}),
                ),
            ),
            resolver=_LoopbackResolverWithPort(port, additional_ports=(port + 1_000,)),
        )
        http_client = PinnedAioHttpJsonClient(ssl_context=self._client_ssl_context)
        source_reader = NacosRuleSourceReader(policy, http_client)
        writer = NacosRuleSourceWriter(
            policy,
            source_reader,
            http_client=http_client,
            grpc_client=NacosGrpcTransport(
                NacosGrpcTlsCredentials(root_certificates=self._grpc_ca_certificate_pem)
            ),
        )
        snapshot_reader = create_registered_source_rule_set_snapshot_reader(
            binding_reader=SqlAlchemyRuleBindingDirectoryReader(engine),
            target_reader=SqlAlchemyRulePublicationTargetReader(engine),
            connection_resolver=ResolveRegisteredSourceConnection(
                SqlAlchemyRegisteredSourceStore(
                    engine,
                    secret_cipher=cipher,
                    fingerprint_keys={"nacos-catalog-v1": b"f" * 32},
                    active_fingerprint_key_id="nacos-catalog-v1",
                )
            ),
            target_policies={ConfigurationSourceProvider.NACOS: policy},
            ssl_context=self._client_ssl_context,
            clock=lambda: now,
        )
        projection = SqlAlchemyRuleCatalogProjection(engine, clock=lambda: now)
        refresher = RefreshRuleCatalog(projection, snapshot_reader, clock=lambda: now)
        initial_rules = (
            b'[{"resource":"POST /api/orders","limitApp":"default",'
            b'"grade":1,"count":25,"strategy":0,"controlBehavior":0,'
            b'"clusterMode":false}]'
        )
        updated_rules = (
            b'[{"resource":"POST /api/orders","limitApp":"default",'
            b'"grade":1,"count":17,"strategy":0,"controlBehavior":0,'
            b'"clusterMode":false}]'
        )
        try:
            await upgrade_database(engine)
            async with engine.begin() as sql:
                await sql.execute(
                    insert(AccountRecord).values(
                        account_id=owner_id,
                        username=owner_name,
                        username_key=hashlib.sha256(uuid4().bytes).hexdigest(),
                        password_hash="$argon2id$synthetic-hash",
                        role_id="admin",
                        status="active",
                        built_in=True,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await sql.execute(
                    insert(RegisteredConfigurationSourceRecord).values(
                        source_id=source_id,
                        revision=source_revision,
                        name="Disposable authenticated Nacos",
                        endpoint=self.endpoint,
                        provider=ConfigurationSourceProvider.NACOS.value,
                        location="public",
                        authentication_mode="direct",
                        credential_configured=True,
                        credential_cipher_format=encrypted.format.value,
                        credential_key_id=encrypted.key_id,
                        credential_payload=encrypted.payload,
                        created_at=now,
                        updated_at=now,
                        updated_by_account_id=owner_id,
                    )
                )
                await sql.execute(
                    insert(RuleBindingRecord).values(
                        binding_id=binding_id,
                        environment_id="e2e-live",
                        app_id="nacos-catalog-app",
                        kind=RuleKind.FLOW.value,
                        profile="sentinel-python-v1",
                        source_id=source_id,
                        location=target_location(target),
                        created_at=now,
                        updated_at=now,
                    )
                )
                await sql.execute(
                    insert(RulePublicationTargetRecord).values(
                        binding_id=binding_id,
                        source_id=source_id,
                        target_revision=f"nacos-catalog-target-{uuid4().hex}",
                        source_revision=source_revision,
                        target_body=target_body(target),
                        updated_at=now,
                    )
                )
                await sql.execute(
                    insert(RuleBindingRecord).values(
                        binding_id=managed_binding_id,
                        environment_id="e2e-live",
                        app_id="nacos-managed-catalog-app",
                        kind=RuleKind.FLOW.value,
                        profile="sentinel-java-v1",
                        source_id=source_id,
                        location=target_location(managed_target),
                        created_at=now,
                        updated_at=now,
                    )
                )
                await sql.execute(
                    insert(RulePublicationTargetRecord).values(
                        binding_id=managed_binding_id,
                        source_id=source_id,
                        target_revision=f"nacos-managed-catalog-target-{uuid4().hex}",
                        source_revision=source_revision,
                        target_body=target_body(managed_target),
                        updated_at=now,
                    )
                )

            await writer.write(
                NacosRuleSourceWrite(connection, target, None, initial_rules)
            )
            managed_payload = (
                b'[{"resource":"POST /api/managed-orders","grade":1,'
                b'"count":25,"strategy":0,"controlBehavior":0,'
                b'"clusterMode":false}]'
            )
            managed_version_id = f"nacos-managed-version-{uuid4().hex}"
            managed_envelope = ManagedRulePublicationV1(
                binding_id=managed_binding_id,
                publication_id=f"nacos-managed-publication-{uuid4().hex}",
                target_version_id=managed_version_id,
                publication_sequence=1,
                rule_kind=ManagedRuleKind.FLOW,
                profile_id="sentinel-java-v1",
                payload_sha256=hashlib.sha256(managed_payload).hexdigest(),
                rule_payload=managed_payload,
            )
            await writer.write(
                NacosRuleSourceWrite(
                    connection,
                    managed_target,
                    None,
                    encode_managed_rule_publication(managed_envelope),
                )
            )
            verified_snapshot = await snapshot_reader.read_rule_set_snapshot(binding_id)
            self.assertEqual(verified_snapshot.binding.id, binding_id)
            managed_snapshot = await snapshot_reader.read_rule_set_snapshot(
                managed_binding_id
            )
            self.assertEqual(managed_snapshot.binding.id, managed_binding_id)
            self.assertEqual(managed_snapshot.binding.profile, "sentinel-java-v1")
            self.assertEqual(managed_snapshot.version_id, managed_version_id)
            self.assertEqual(len(managed_snapshot.records), 1)
            self.assertEqual(
                managed_snapshot.records[0].rule.resource,
                "POST /api/managed-orders",
            )
            managed_refresh = await refresher.execute(
                "e2e-live", "nacos-managed-catalog-app"
            )
            managed_query = RuleCatalogQuery(
                "e2e-live", "nacos-managed-catalog-app", None, "", 1, 20
            )
            managed_page = await projection.read_catalog(managed_query)
            self.assertEqual(managed_refresh.bindings_current, 1)
            self.assertEqual(managed_page.coverage.value, "complete")
            self.assertEqual(managed_page.total, 1)
            self.assertEqual(
                managed_page.items[0].record.rule.resource,
                "POST /api/managed-orders",
            )
            first = await refresher.execute("e2e-live", "nacos-catalog-app")
            query = RuleCatalogQuery("e2e-live", "nacos-catalog-app", None, "", 1, 20)
            first_page = await projection.read_catalog(query)
            self.assertEqual(
                first.bindings_current, 1, repr((first, first_page.issues))
            )
            self.assertEqual(first_page.coverage.value, "complete")
            self.assertEqual(
                first_page.items[0].record.rule.resource, "POST /api/orders"
            )
            self.assertEqual(first_page.items[0].record.rule.count, 25)
            self.assertTrue(first_page.items[0].source_revision)
            original_checksum = first_page.items[0].checksum
            self.assertNotIn(_ADMIN_PASSWORD, repr(connection))
            self.assertNotIn(_ADMIN_PASSWORD, repr(first_page))

            baseline = await source_reader.read(connection, target)
            await writer.write(
                NacosRuleSourceWrite(connection, target, baseline.md5, updated_rules)
            )
            second = await refresher.execute("e2e-live", "nacos-catalog-app")
            updated_page = await projection.read_catalog(query)
            self.assertEqual(second.bindings_current, 1)
            self.assertEqual(updated_page.items[0].record.rule.count, 17)
            self.assertNotEqual(updated_page.items[0].checksum, original_checksum)

            from httpx import ASGITransport, AsyncClient

            from atlas_richie.sentinel_console.app import build_app
            from atlas_richie.sentinel_console.application.read_rule_binding_states import (
                ReadRuleBindingStates,
            )
            from atlas_richie.sentinel_console.application.read_rule_catalog import (
                ReadRuleCatalog,
            )
            from atlas_richie.sentinel_console.domain.session import (
                ActiveAccountSession,
            )
            from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
                SqlAlchemyRuleBindingDirectoryReader,
            )
            from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_state_reader import (
                SqlAlchemyRuleBindingStateReader,
            )
            from support.rule_catalog_page_runner import (
                verify_mounted_rule_catalog_page,
            )

            class InitializedReader:
                async def is_initialized(self):
                    return True

            class SetupWindowReader:
                async def is_setup_window_open(self):
                    return False

            class OperatorVerifier:
                async def is_current_operator(self, opaque_session):
                    return False

            class AdminSessionReader:
                async def read_active_session(self, session_digest):
                    return ActiveAccountSession(
                        owner_id, owner_name, "admin", "nacos-catalog-session-epoch"
                    )

            binding_directory = SqlAlchemyRuleBindingDirectoryReader(engine)
            api = build_app(
                bootstrap_initialization_reader=InitializedReader(),
                setup_window_reader=SetupWindowReader(),
                bootstrap_operator_verifier=OperatorVerifier(),
                current_session_reader=AdminSessionReader(),
                current_session_revoker=object(),
                account_directory_reader=object(),
                allowed_browser_origins=frozenset(
                    {"https://console.test", "http://localhost:5173"}
                ),
                rule_binding_reader=binding_directory,
                rule_binding_scope_reader=binding_directory,
                rule_catalog_reader=ReadRuleCatalog(projection),
                rule_catalog_refresher=refresher,
                rule_binding_state_reader=ReadRuleBindingStates(
                    SqlAlchemyRuleBindingStateReader(engine, clock=lambda: now)
                ),
            )
            async with AsyncClient(
                transport=ASGITransport(app=api), base_url="http://console.test"
            ) as client:
                client.cookies.set(
                    "sentinel_session", "nacos-catalog-session-token-000000000001"
                )
                api_read = await client.get(
                    "/api/v2/rules/catalog?environmentId=e2e-live&appId="
                    "nacos-catalog-app&page=1&pageSize=20",
                    headers={"x-request-id": "nacos-rule-catalog-api-1"},
                )
            self.assertEqual(api_read.status_code, 200, api_read.text)
            self.assertEqual(api_read.json()["coverage"], "complete")
            self.assertEqual(
                api_read.json()["items"][0]["record"]["rule"]["value"]["count"],
                17,
            )
            self.assertNotIn(_ADMIN_PASSWORD, api_read.text)
            async with AsyncClient(
                transport=ASGITransport(app=api), base_url="http://console.test"
            ) as managed_client:
                managed_client.cookies.set(
                    "sentinel_session", "nacos-catalog-session-token-000000000001"
                )
                managed_api_read = await managed_client.get(
                    "/api/v2/rules/catalog?environmentId=e2e-live&appId="
                    "nacos-managed-catalog-app&page=1&pageSize=20",
                    headers={"x-request-id": "nacos-managed-rule-catalog-api-1"},
                )
            self.assertEqual(managed_api_read.status_code, 200, managed_api_read.text)
            self.assertEqual(managed_api_read.json()["coverage"], "complete")
            self.assertEqual(managed_api_read.json()["total"], 1)
            self.assertEqual(
                managed_api_read.json()["items"][0]["record"]["rule"]["value"][
                    "resource"
                ],
                "POST /api/managed-orders",
            )
            self.assertNotIn(_ADMIN_PASSWORD, managed_api_read.text)

            await verify_mounted_rule_catalog_page(
                api,
                environment_id="e2e-live",
                app_id="nacos-catalog-app",
                resource="POST /api/orders",
                source_label="Disposable authenticated Nacos",
            )

            async def read_binding_state() -> dict[str, object]:
                async with AsyncClient(
                    transport=ASGITransport(app=api), base_url="http://console.test"
                ) as client:
                    client.cookies.set(
                        "sentinel_session", "nacos-catalog-session-token-000000000001"
                    )
                    response = await client.get(
                        "/api/v2/rules/catalog/binding-states?environmentId=e2e-live&appId=nacos-catalog-app&kind=flow&page=1&pageSize=20",
                        headers={"x-request-id": "nacos-rule-binding-state-1"},
                    )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["total"], 1)
                return response.json()["items"][0]

            empty_baseline = await source_reader.read(connection, target)
            await writer.write(
                NacosRuleSourceWrite(connection, target, empty_baseline.md5, b"[]")
            )
            empty_refresh = await refresher.execute("e2e-live", "nacos-catalog-app")
            empty_page = await projection.read_catalog(query)
            empty_state = await read_binding_state()
            self.assertEqual(empty_refresh.bindings_current, 1)
            self.assertEqual(empty_page.coverage.value, "complete")
            self.assertEqual(empty_page.total, 0)
            self.assertEqual(empty_state["state"], "configured_empty")
            self.assertEqual(empty_state["ruleCount"], 0)

            restored_baseline = await source_reader.read(connection, target)
            await writer.write(
                NacosRuleSourceWrite(
                    connection, target, restored_baseline.md5, updated_rules
                )
            )
            restored = await refresher.execute("e2e-live", "nacos-catalog-app")
            self.assertEqual(restored.bindings_current, 1)

            baseline = await source_reader.read(connection, target)
            await writer.write(
                NacosRuleSourceWrite(
                    connection,
                    target,
                    baseline.md5,
                    b'{"not":"a rule array"}',
                )
            )
            third = await refresher.execute("e2e-live", "nacos-catalog-app")
            retained = await projection.read_catalog(query)
            self.assertEqual(third.bindings_stale, 1)
            self.assertEqual(retained.coverage.value, "partial")
            self.assertEqual(retained.items[0].record.rule.count, 17)
            self.assertEqual(retained.items[0].freshness.value, "stale")
            self.assertEqual(retained.issues[0].reason.value, "content_invalid")
            invalid_state = await read_binding_state()
            self.assertEqual(invalid_state["state"], "content_invalid")
            self.assertEqual(invalid_state["freshness"], "stale")
            self.assertTrue(invalid_state["hasLastKnownGood"])

            await asyncio.to_thread(
                subprocess.run,
                ["docker", "stop", self.container_name],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self._started = False
            fourth = await refresher.execute("e2e-live", "nacos-catalog-app")
            unavailable = await projection.read_catalog(query)
            self.assertEqual(fourth.bindings_stale, 1)
            self.assertEqual(unavailable.items[0].record.rule.count, 17)
            self.assertEqual(unavailable.items[0].freshness.value, "stale")
            self.assertEqual(unavailable.issues[0].reason.value, "source_unavailable")
        finally:
            if self._started:
                self._remove_container()
            await engine.dispose()

    async def test_authenticated_update_cas_uses_real_nacos_grpc_and_readback(
        self,
    ) -> None:
        proxy_port = self._proxy_port
        target_policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    _TLS_HOSTNAME,
                    ("127.0.0.1/32",),
                    frozenset({proxy_port, proxy_port + 1_000}),
                ),
            ),
            resolver=_LoopbackResolverWithPort(
                proxy_port, additional_ports=(proxy_port + 1_000,)
            ),
        )
        http_client = PinnedAioHttpJsonClient(ssl_context=self._client_ssl_context)
        reader = NacosRuleSourceReader(target_policy, http_client)
        writer = NacosRuleSourceWriter(
            target_policy,
            reader,
            http_client=http_client,
            grpc_client=NacosGrpcTransport(
                NacosGrpcTlsCredentials(root_certificates=self._grpc_ca_certificate_pem)
            ),
        )
        source_id = f"nacos-grpc-auth-{uuid4().hex}"
        target = NacosRulePublicationTarget(
            binding_id=f"binding-{uuid4().hex}",
            source_id=source_id,
            namespace="public",
            group="SENTINEL_GRPC_AUTH_ACCEPTANCE",
            data_id=f"sentinel-grpc-auth-{uuid4().hex}.json",
        )
        connection = SourceConnectionInput(
            source_id=source_id,
            expected_revision="disposable-auth-source-revision",
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.DIRECT,
            username="nacos",
            password=_ADMIN_PASSWORD,
        )
        initial = b'{"version":"authenticated-initial"}'
        create_receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=None,
                value=initial,
            )
        )
        baseline = await reader.read(connection, target)
        self.assertEqual(baseline.value, initial)
        self.assertEqual(baseline.md5, create_receipt.md5)

        candidate = b'{"version":"authenticated-grpc-cas"}'
        update_receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=baseline.md5,
                value=candidate,
            )
        )
        self.assertEqual(
            update_receipt.md5,
            hashlib.md5(candidate, usedforsecurity=False).hexdigest(),
        )
        actual = await reader.read(connection, target)
        self.assertEqual(actual.value, candidate)
        self.assertEqual(actual.md5, update_receipt.md5)

        with self.assertRaises(NacosRuleSourceConflict):
            await writer.write(
                NacosRuleSourceWrite(
                    connection=connection,
                    target=target,
                    expected_md5=baseline.md5,
                    value=b'{"version":"authenticated-stale-cas"}',
                )
            )

        self.assertNotIn(_ADMIN_PASSWORD, repr(connection))
        self.assertNotIn(_ADMIN_PASSWORD, repr(actual))

    async def test_credential_reference_resolves_for_authenticated_grpc_update_cas(
        self,
    ) -> None:
        connect_args = {}
        database_url = (
            _MYSQL_DATABASE_URL
            or _POSTGRES_DATABASE_URL
            or "sqlite+aiosqlite:///:memory:"
        )
        if _MYSQL_DATABASE_URL is not None:
            root_certificate = os.environ.get("SENTINEL_CONSOLE_MYSQL_ROOT_CERTIFICATE")
            if not root_certificate:
                self.fail("disposable MySQL acceptance requires its temporary CA")
            connect_args["ssl"] = ssl.create_default_context(cafile=root_certificate)
        elif _POSTGRES_DATABASE_URL is not None:
            root_certificate = os.environ.get(
                "SENTINEL_CONSOLE_POSTGRESQL_ROOT_CERTIFICATE"
            )
            if not root_certificate:
                self.fail("disposable PostgreSQL acceptance requires its temporary CA")
            connect_args.update(
                sslmode="verify-full",
                sslrootcert=root_certificate,
            )
        engine = create_async_engine(database_url, connect_args=connect_args)
        self.addAsyncCleanup(engine.dispose)
        await upgrade_database(engine)
        store = SqlAlchemyRegisteredSourceStore(
            engine,
            secret_cipher=AesGcmSecretCipher(
                "acceptance-key", {"acceptance-key": b"k" * 32}
            ),
            fingerprint_keys={"acceptance": b"f" * 32},
            active_fingerprint_key_id="acceptance",
        )
        actor_id = "nacos-reference-operator"
        session_token = "nacos-reference-session-token"
        csrf_token = "nacos-reference-csrf-token"
        session_digest = hashlib.sha256(session_token.encode("ascii")).hexdigest()
        csrf_digest = hashlib.sha256(csrf_token.encode("ascii")).hexdigest()
        now = datetime.now(UTC)
        async with engine.begin() as sql_connection:
            await sql_connection.execute(
                insert(AccountRecord).values(
                    account_id=actor_id,
                    username="nacos-reference-admin",
                    username_key="a" * 64,
                    password_hash="$argon2id$acceptance-only",
                    role_id="admin",
                    status="active",
                    built_in=True,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            await sql_connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=session_digest,
                    account_id=actor_id,
                    session_epoch="nacos-reference-epoch",
                    csrf_hash=csrf_digest,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=None,
                )
            )

        proxy_port = self._proxy_port
        target_policy = RegisteredSourceTargetPolicy(
            (
                RegisteredSourceTargetRule.create(
                    ConfigurationSourceProvider.NACOS,
                    _TLS_HOSTNAME,
                    ("127.0.0.1/32",),
                    frozenset({proxy_port, proxy_port + 1_000}),
                ),
            ),
            resolver=_LoopbackResolverWithPort(
                proxy_port, additional_ports=(proxy_port + 1_000,)
            ),
        )
        http_client = PinnedAioHttpJsonClient(ssl_context=self._client_ssl_context)
        reader = NacosRuleSourceReader(target_policy, http_client)
        writer = NacosRuleSourceWriter(
            target_policy,
            reader,
            http_client=http_client,
            grpc_client=NacosGrpcTransport(
                NacosGrpcTlsCredentials(root_certificates=self._grpc_ca_certificate_pem)
            ),
        )
        reference = "secret://sentinel/acceptance/nacos-admin"
        candidate_source = SourceConnectionInput(
            source_id=None,
            expected_revision=None,
            provider=ConfigurationSourceProvider.NACOS,
            endpoint=self.endpoint,
            location="public",
            authentication_mode=SourceCheckAuthenticationMode.CREDENTIAL_REFERENCE,
            credential_reference=reference,
        )
        registration = await store.mutate(
            RegisteredSourceMutation(
                kind=SourceMutationKind.REGISTER,
                request_key=f"nacos-reference-{uuid4().hex}",
                name="Nacos credential-reference acceptance",
                source=candidate_source,
            ),
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"request-{uuid4().hex}",
            now=now,
        )
        self.assertIs(registration.status, SourceMutationStatus.COMPLETED)
        assert registration.record is not None
        source_id = registration.record.id
        source_revision = registration.record.revision
        async with engine.connect() as sql_connection:
            persisted = (
                (
                    await sql_connection.execute(
                        select(RegisteredConfigurationSourceRecord.__table__).where(
                            RegisteredConfigurationSourceRecord.source_id == source_id
                        )
                    )
                )
                .mappings()
                .one()
            )
        self.assertNotIn(reference.encode("utf-8"), persisted["credential_payload"])

        target = NacosRulePublicationTarget(
            binding_id=f"binding-{uuid4().hex}",
            source_id=source_id,
            namespace="public",
            group="SENTINEL_GRPC_REFERENCE_ACCEPTANCE",
            data_id=f"sentinel-grpc-reference-{uuid4().hex}.json",
        )
        secret_resolver = _NacosCredentialReferenceResolver(reference)
        connection = await ResolveRegisteredSourceConnection(
            store,
            secret_resolver,
        ).execute(source_id, source_revision, ConfigurationSourceProvider.NACOS)

        self.assertIs(
            connection.authentication_mode, SourceCheckAuthenticationMode.DIRECT
        )
        self.assertEqual(connection.username, "nacos")
        self.assertIsNone(connection.credential_reference)
        self.assertNotIn(_ADMIN_PASSWORD, repr(connection))
        self.assertEqual(secret_resolver.references, [reference])

        initial = b'{"version":"reference-initial"}'
        baseline_receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=None,
                value=initial,
            )
        )
        baseline = await reader.read(connection, target)
        self.assertEqual(baseline.value, initial)
        self.assertEqual(baseline.md5, baseline_receipt.md5)

        candidate = b'{"version":"reference-grpc-cas"}'
        receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=target,
                expected_md5=baseline.md5,
                value=candidate,
            )
        )
        actual = await reader.read(connection, target)
        self.assertEqual(actual.value, candidate)
        self.assertEqual(actual.md5, receipt.md5)
        self.assertNotIn(_ADMIN_PASSWORD, repr(actual))

        # Exercise the production SQL outbox composition with the same opaque
        # source reference. The worker must resolve the exact encrypted SQL
        # source revision before its authenticated Nacos CAS and read-back.
        worker_binding_id = f"binding-{uuid4().hex}"
        baseline_candidate = _flow_candidate(worker_binding_id, count=7)
        baseline_checksum = candidate_checksum(baseline_candidate)
        publish_candidate = _flow_candidate(
            worker_binding_id,
            count=11,
            base_version_id=f"baseline-{uuid4().hex}",
            base_checksum=baseline_checksum,
        )
        publish_checksum = candidate_checksum(publish_candidate)
        baseline_version_id = publish_candidate.base_version_id
        assert baseline_version_id is not None
        baseline_validation_id = f"validation-{uuid4().hex}"
        publish_version_id = f"version-{uuid4().hex}"
        publish_validation_id = f"validation-{uuid4().hex}"
        now = datetime.now(UTC)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        async with engine.begin() as sql_connection:
            for validation_id, rule_candidate, checksum in (
                (baseline_validation_id, baseline_candidate, baseline_checksum),
                (publish_validation_id, publish_candidate, publish_checksum),
            ):
                await sql_connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=validation_id,
                        binding_id=worker_binding_id,
                        profile="sentinel-profile-v1",
                        base_checksum=rule_candidate.base_checksum,
                        candidate_checksum=checksum,
                        is_publishable=True,
                        issues=[],
                        actor_account_id=actor_id,
                        request_id=f"request-{validation_id}",
                        created_at=now,
                    )
                )
            for (
                version_id,
                base_version_id,
                validation_id,
                rule_candidate,
                checksum,
                name,
            ) in (
                (
                    baseline_version_id,
                    None,
                    baseline_validation_id,
                    baseline_candidate,
                    baseline_checksum,
                    "Nacos worker baseline",
                ),
                (
                    publish_version_id,
                    baseline_version_id,
                    publish_validation_id,
                    publish_candidate,
                    publish_checksum,
                    "Nacos worker credential-reference publish",
                ),
            ):
                await sql_connection.execute(
                    insert(RuleSetVersionRecord).values(
                        version_id=version_id,
                        binding_id=worker_binding_id,
                        kind=rule_candidate.kind.value,
                        profile="sentinel-profile-v1",
                        base_version_id=base_version_id,
                        checksum=checksum,
                        name=name,
                        note="",
                        validation_id=validation_id,
                        records=[
                            rule_record_body(
                                RuleRecord(
                                    "worker-record",
                                    rule_candidate.rules[0].rule,
                                )
                            )
                        ],
                        created_at=now,
                        created_by_account_id=actor_id,
                    )
                )

        worker_target = NacosRulePublicationTarget(
            binding_id=worker_binding_id,
            source_id=source_id,
            namespace="public",
            group="SENTINEL_AUTH_OUTBOX_ACCEPTANCE",
            data_id=f"sentinel-auth-outbox-{uuid4().hex}.json",
        )
        worker_target_reader = _SourceBoundTargetReader(worker_target, source_revision)
        mutation_store = SqlAlchemyRuleMutationStore(
            engine,
            fingerprint_keys={"acceptance": b"r" * 32},
            active_fingerprint_key_id="acceptance",
            binding_reader=_SourceBoundBindingReader(source_id),
            publication_target_reader=worker_target_reader,
        )
        worker_request_key = f"worker-publish-{uuid4().hex}"
        worker_checksum = publish_checksum
        accepted = await mutation_store.mutate(
            RuleMutationCommand(
                binding_id=worker_binding_id,
                request_key=worker_request_key,
                mutation=PublishRuleVersion(
                    version_id=publish_version_id,
                    version_checksum=worker_checksum,
                    expected_version_id=baseline_version_id,
                    expected_checksum=baseline_checksum,
                    expected_source_revision=source_revision,
                    reason="authenticated outbox acceptance",
                ),
            ),
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"request-{worker_request_key}",
            now=now,
        )
        self.assertIs(accepted.status, RuleOperationStatus.PENDING)

        version_reader = SqlAlchemyRuleVersionReader(engine)
        baseline_version = await version_reader.read_rule_version(
            worker_binding_id, baseline_version_id
        )
        expected_baseline = SentinelRuleVersionJsonEncoder(
            "sentinel-profile-v1"
        ).encode_rule_version(baseline_version)
        reset_receipt = await writer.write(
            NacosRuleSourceWrite(
                connection=connection,
                target=worker_target,
                expected_md5=None,
                value=expected_baseline,
            )
        )
        self.assertIsNotNone(reset_receipt.md5)

        def create_worker(clock):
            return create_nacos_rule_publication_worker(
                engine,
                target_policy=target_policy,
                credential_resolver=store,
                credential_reference_resolver=secret_resolver,
                profile_id="sentinel-profile-v1",
                ssl_context=self._client_ssl_context,
                grpc_tls_credentials=NacosGrpcTlsCredentials(
                    root_certificates=self._grpc_ca_certificate_pem
                ),
                clock=clock,
            )

        worker = create_worker(lambda: now + timedelta(seconds=1))
        worker_outcomes = await worker.run_once()
        worker_operation = await mutation_store.read_operation(
            worker_binding_id,
            worker_request_key,
            actor_id=actor_id,
            session_digest=session_digest,
        )
        self.assertEqual(
            worker_outcomes,
            (RulePublicationWorkerOutcome.COMPLETED,),
            repr(worker_operation),
        )
        published_version = await version_reader.read_rule_version(
            worker_binding_id, publish_version_id
        )
        expected_published = SentinelRuleVersionJsonEncoder(
            "sentinel-profile-v1"
        ).encode_rule_version(published_version)
        published = await reader.read(connection, worker_target)
        self.assertEqual(published.value, expected_published)
        self.assertEqual(secret_resolver.references, [reference, reference])
        self.assertNotIn(_ADMIN_PASSWORD, repr(worker))

        # The scheduled activation and restoration phases must use the same
        # frozen SQL source revision and credential-reference resolver as a
        # direct publication; both phases are published by the actual outbox
        # worker and advance only after provider read-back.
        plan_request_key = f"worker-plan-{uuid4().hex}"
        plan_created = await mutation_store.mutate(
            RuleMutationCommand(
                binding_id=worker_binding_id,
                request_key=plan_request_key,
                mutation=CreateRuleActivationPlan(
                    version_id=baseline_version_id,
                    restore_version_id=publish_version_id,
                    activate_at=now + timedelta(seconds=62),
                    deactivate_at=now + timedelta(seconds=200),
                    time_zone="UTC",
                ),
            ),
            actor_id=actor_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"request-{plan_request_key}",
            now=now + timedelta(seconds=61),
        )
        self.assertIs(plan_created.status, RuleOperationStatus.COMPLETED)
        plan_id = plan_created.result.id
        plan_scheduler = RunRuleActivationPlanWorker(
            work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
            publication_enqueuer=mutation_store,
            clock=lambda: now + timedelta(seconds=63),
        )
        self.assertEqual(
            await plan_scheduler.run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        plan_reader = SqlAlchemyRuleActivationPlanReader(engine)
        activation = await plan_reader.read_rule_activation_plans(worker_binding_id)
        self.assertEqual(activation.items[0].id, plan_id)
        self.assertEqual(activation.items[0].state.value, "activating")
        original_grpc_request = NacosGrpcTransport.request
        activation_ack_losses = 0

        async def apply_activation_then_drop_ack(
            transport: NacosGrpcTransport,
            pinned_target,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ):
            nonlocal activation_ack_losses
            response = await original_grpc_request(
                transport,
                pinned_target,
                request_type=request_type,
                body=body,
                headers=headers,
            )
            if request_type == "ConfigPublishRequest":
                activation_ack_losses += 1
                raise NacosGrpcOutcomeUnknown
            return response

        with patch.object(
            NacosGrpcTransport,
            "request",
            new=apply_activation_then_drop_ack,
        ):
            activation_outcomes = await create_worker(
                lambda: now + timedelta(seconds=64)
            ).run_once()
        self.assertEqual(
            activation_outcomes,
            (RulePublicationWorkerOutcome.UNKNOWN,),
        )
        self.assertEqual(activation_ack_losses, 1)
        activated = await reader.read(connection, worker_target)
        self.assertEqual(activated.value, expected_baseline)
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=mutation_store,
                clock=lambda: now + timedelta(seconds=124),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        activation_recovery_publish_attempts = 0

        async def count_activation_recovery_publish(
            transport: NacosGrpcTransport,
            pinned_target,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ):
            nonlocal activation_recovery_publish_attempts
            if request_type == "ConfigPublishRequest":
                activation_recovery_publish_attempts += 1
            return await original_grpc_request(
                transport,
                pinned_target,
                request_type=request_type,
                body=body,
                headers=headers,
            )

        with patch.object(
            NacosGrpcTransport,
            "request",
            new=count_activation_recovery_publish,
        ):
            activation_recovery_outcomes = await create_worker(
                lambda: now + timedelta(seconds=125)
            ).run_once()
        self.assertEqual(
            activation_recovery_outcomes,
            (RulePublicationWorkerOutcome.COMPLETED,),
        )
        self.assertEqual(activation_recovery_publish_attempts, 0)
        self.assertEqual(
            await reader.read(connection, worker_target),
            activated,
        )
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=mutation_store,
                clock=lambda: now + timedelta(seconds=185),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )
        self.assertEqual(
            (await plan_reader.read_rule_activation_plans(worker_binding_id))
            .items[0]
            .state.value,
            "active",
        )

        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=mutation_store,
                clock=lambda: now + timedelta(seconds=201),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        restoration_ack_losses = 0

        async def apply_restoration_then_drop_ack(
            transport: NacosGrpcTransport,
            pinned_target,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ):
            nonlocal restoration_ack_losses
            response = await original_grpc_request(
                transport,
                pinned_target,
                request_type=request_type,
                body=body,
                headers=headers,
            )
            if request_type == "ConfigPublishRequest":
                restoration_ack_losses += 1
                raise NacosGrpcOutcomeUnknown
            return response

        with patch.object(
            NacosGrpcTransport,
            "request",
            new=apply_restoration_then_drop_ack,
        ):
            restoration_outcomes = await create_worker(
                lambda: now + timedelta(seconds=202)
            ).run_once()
        self.assertEqual(
            restoration_outcomes,
            (RulePublicationWorkerOutcome.UNKNOWN,),
        )
        self.assertEqual(restoration_ack_losses, 1)
        restored = await reader.read(connection, worker_target)
        self.assertEqual(restored.value, expected_published)
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=mutation_store,
                clock=lambda: now + timedelta(seconds=263),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.ENQUEUED,),
        )
        restoration_recovery_publish_attempts = 0

        async def count_restoration_recovery_publish(
            transport: NacosGrpcTransport,
            pinned_target,
            *,
            request_type: str,
            body: dict[str, object],
            headers: dict[str, str],
        ):
            nonlocal restoration_recovery_publish_attempts
            if request_type == "ConfigPublishRequest":
                restoration_recovery_publish_attempts += 1
            return await original_grpc_request(
                transport,
                pinned_target,
                request_type=request_type,
                body=body,
                headers=headers,
            )

        with patch.object(
            NacosGrpcTransport,
            "request",
            new=count_restoration_recovery_publish,
        ):
            restoration_recovery_outcomes = await create_worker(
                lambda: now + timedelta(seconds=264)
            ).run_once()
        self.assertEqual(
            restoration_recovery_outcomes,
            (RulePublicationWorkerOutcome.COMPLETED,),
        )
        self.assertEqual(restoration_recovery_publish_attempts, 0)
        self.assertEqual(await reader.read(connection, worker_target), restored)
        self.assertEqual(
            await RunRuleActivationPlanWorker(
                work_queue=SqlAlchemyRuleActivationPlanWorkQueue(engine),
                publication_enqueuer=mutation_store,
                clock=lambda: now + timedelta(seconds=324),
            ).run_once(),
            (RuleActivationPlanWorkerOutcome.COMPLETED,),
        )
        final_plan = await plan_reader.read_rule_activation_plans(worker_binding_id)
        self.assertEqual(final_plan.items[0].state.value, "completed")
        self.assertEqual(
            secret_resolver.references,
            [reference, reference, reference, reference, reference, reference],
        )

    async def _start_tls_proxy(self) -> None:
        certificate, private_key = _create_test_certificate()
        self._grpc_ca_certificate_pem = certificate.encode("utf-8")
        self._certificate_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-nacos-auth-tls-"
        )
        directory = Path(self._certificate_directory.name)
        certificate_path = directory / "certificate.pem"
        key_path = directory / "private-key.pem"
        certificate_path.write_text(certificate, encoding="utf-8")
        key_path.write_text(private_key, encoding="utf-8")
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(
            certfile=str(certificate_path),
            keyfile=str(key_path),
        )
        server_context.set_alpn_protocols(["h2"])
        self._client_ssl_context = ssl.create_default_context(cadata=certificate)

        async def forward(request: web.Request) -> web.Response:
            upstream_url = f"{self.nacos_endpoint}/{request.match_info['tail']}"
            if request.query_string:
                upstream_url = f"{upstream_url}?{request.query_string}"
            excluded_headers = {
                "connection",
                "content-length",
                "host",
                "transfer-encoding",
            }
            headers = {
                key: value
                for key, value in request.headers.items()
                if key.lower() not in excluded_headers
            }
            async with (
                ClientSession(trust_env=False) as session,
                session.request(
                    request.method,
                    upstream_url,
                    headers=headers,
                    data=await request.read(),
                    allow_redirects=False,
                ) as upstream,
            ):
                response_headers = {
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower() not in excluded_headers
                }
                return web.Response(
                    status=upstream.status,
                    headers=response_headers,
                    body=await upstream.read(),
                )

        app = web.Application()
        app.router.add_route("*", "/nacos/{tail:.*}", forward)
        self._proxy_runner = web.AppRunner(app)
        await self._proxy_runner.setup()
        self._proxy_port, self._grpc_proxy_port = _available_nacos_port_pair(
            excluded_ports=frozenset({self._http_port, self._grpc_port})
        )
        site = web.TCPSite(
            self._proxy_runner,
            "127.0.0.1",
            self._proxy_port,
            ssl_context=server_context,
        )
        await site.start()
        self._grpc_proxy_server = await asyncio.start_server(
            self._forward_grpc_tls,
            "127.0.0.1",
            self._grpc_proxy_port,
            ssl=server_context,
        )
        self.endpoint = f"https://{_TLS_HOSTNAME}:{self._proxy_port}/nacos"

    async def _forward_grpc_tls(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        current_task = asyncio.current_task()
        if current_task is not None:
            self._grpc_proxy_tasks.add(current_task)
        upstream_writer: asyncio.StreamWriter | None = None

        async def forward(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            while chunk := await reader.read(64 * 1024):
                writer.write(chunk)
                await writer.drain()

        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                "127.0.0.1", self._grpc_port
            )
            await asyncio.gather(
                forward(client_reader, upstream_writer),
                forward(upstream_reader, client_writer),
            )
        except (ConnectionError, OSError):
            pass
        finally:
            if upstream_writer is not None:
                upstream_writer.close()
            client_writer.close()
            writers = tuple(
                writer
                for writer in (upstream_writer, client_writer)
                if writer is not None
            )
            await asyncio.gather(
                *(writer.wait_closed() for writer in writers),
                return_exceptions=True,
            )
            if current_task is not None:
                self._grpc_proxy_tasks.discard(current_task)

    async def _stop_tls_proxy(self) -> None:
        if self._grpc_proxy_server is not None:
            self._grpc_proxy_server.close()
            await self._grpc_proxy_server.wait_closed()
            if self._grpc_proxy_tasks:
                _, pending = await asyncio.wait(
                    tuple(self._grpc_proxy_tasks), timeout=2
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            self._grpc_proxy_server = None
        if self._proxy_runner is not None:
            await self._proxy_runner.cleanup()
            self._proxy_runner = None
        if self._certificate_directory is not None:
            self._certificate_directory.cleanup()
            self._certificate_directory = None

    def _initialize_admin(self) -> None:
        request = Request(
            f"{self.nacos_endpoint}/v3/auth/user/admin",
            data=f"password={_ADMIN_PASSWORD}".encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        deadline = time.monotonic() + 90
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urlopen(request, timeout=3) as response:
                    payload = json.loads(response.read())
                    if response.status == 200 and payload.get("code") == 0:
                        return
                    last_error = RuntimeError("Nacos admin initialization was rejected")
            except HTTPError as error:
                if error.code not in {502, 503, 504}:
                    last_error = RuntimeError(
                        "Nacos admin initialization returned an unexpected response"
                    )
                else:
                    last_error = error
            except (OSError, URLError, TimeoutError, ValueError) as error:
                last_error = error
            time.sleep(0.5)
        raise AssertionError(
            "disposable authenticated Nacos did not initialize its admin user"
        ) from last_error

    def _remove_container(self) -> None:
        if self._started:
            subprocess.run(
                ["docker", "rm", "--force", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self._started = False


def _create_test_certificate() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, _TLS_HOSTNAME),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(_TLS_HOSTNAME),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return certificate_pem, private_key_pem


def _available_nacos_port_pair(
    *, excluded_ports: frozenset[int] = frozenset()
) -> tuple[int, int]:
    """Reserve a free loopback HTTP/gRPC port pair with Nacos's +1000 offset."""
    # The host may have many ephemeral ports occupied independently, and a
    # usable Nacos pair must also have the fixed +1000 gRPC partner free.
    # Retry enough candidates to avoid turning ordinary local port pressure
    # into a fixture-startup failure before the acceptance reaches its SUT.
    for _ in range(4_096):
        with socket.socket() as http_socket, socket.socket() as grpc_socket:
            http_socket.bind(("127.0.0.1", 0))
            http_port = http_socket.getsockname()[1]
            grpc_port = http_port + 1_000
            if grpc_port > 65_535 or {http_port, grpc_port} & excluded_ports:
                continue
            try:
                grpc_socket.bind(("127.0.0.1", grpc_port))
            except OSError:
                continue
        return http_port, grpc_port
    raise RuntimeError("could not reserve an adjacent Nacos HTTP/gRPC port pair")


class _LoopbackResolverWithPort:
    """Resolve only the test hostname and explicitly selected ephemeral port."""

    def __init__(self, port: int, *, additional_ports: Sequence[int] = ()) -> None:
        self._ports = frozenset((port, *additional_ports))

    async def __call__(self, hostname: str, port: int) -> Sequence[tuple]:
        if hostname != _TLS_HOSTNAME or port not in self._ports:
            raise OSError("unexpected authenticated Nacos destination")
        return (
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("127.0.0.1", port),
            ),
        )


class _NacosCredentialReferenceResolver:
    def __init__(self, reference: str) -> None:
        self._reference = reference
        self.references: list[str] = []

    async def resolve(
        self,
        provider: ConfigurationSourceProvider,
        reference: str,
    ) -> ResolvedSourceCredentials | None:
        self.references.append(reference)
        if (
            provider is not ConfigurationSourceProvider.NACOS
            or reference != self._reference
        ):
            return None
        return ResolvedSourceCredentials(
            provider=provider,
            username="nacos",
            password=_ADMIN_PASSWORD,
        )


def _flow_candidate(
    binding_id: str,
    *,
    count: int,
    base_version_id: str | None = None,
    base_checksum: str = "sha256:worker-root",
):
    return parse_rule_candidate(
        {
            "bindingId": binding_id,
            "profile": "sentinel-profile-v1",
            "kind": "flow",
            "baseVersionId": base_version_id,
            "baseChecksum": base_checksum,
            "sourceRevision": None,
            "rules": [
                {
                    "recordId": "worker-record",
                    "rule": {
                        "kind": "flow",
                        "value": {
                            "resource": "/credential-reference-worker",
                            "limitApp": "default",
                            "grade": 1,
                            "count": count,
                            "strategy": 0,
                            "controlBehavior": 0,
                            "clusterMode": False,
                        },
                    },
                }
            ],
        }
    )


class _SourceBoundBindingReader:
    def __init__(self, source_id: str) -> None:
        self._source_id = source_id

    async def read_rule_binding(self, binding_id: str) -> RuleBinding:
        return RuleBinding(
            id=binding_id,
            environment_id="acceptance",
            app_id="acceptance-app",
            kind=RuleKind.FLOW,
            profile="sentinel-profile-v1",
            source_id=self._source_id,
            source_label="Disposable authenticated Nacos",
            location="public",
        )


class _SourceBoundTargetReader:
    def __init__(
        self, target: NacosRulePublicationTarget, source_revision: str
    ) -> None:
        self._target = target
        self._source_revision = source_revision

    async def read_rule_publication_target(self, binding_id: str):
        if binding_id != self._target.binding_id:
            return None
        return VersionedRulePublicationTarget(
            revision="credential-reference-worker-target-v1",
            source_revision=self._source_revision,
            target=self._target,
        )


if __name__ == "__main__":
    unittest.main()
