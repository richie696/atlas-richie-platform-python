"""Installed CLI acceptance for one SQL outbox serving Nacos and Consul."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import ssl
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import test_installed_cli_bootstrap_acceptance as bootstrap_acceptance
import test_registered_source_nacos_auth_acceptance as nacos_auth_acceptance
from consul_acl_test_support import DisposableConsulAclServer
from rule_publication_nacos_database_acceptance import (
    _CONTAINER_OWNER_LABEL,
    _GROUP,
    _PROFILE,
    _candidate,
    _free_loopback_port_pair,
    _remove_owned_container,
    _wait_for_nacos,
)
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from atlas_richie.sentinel_console.api.rule_snapshot_serializers import (
    rule_record_body,
)
from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.application.mutate_rule_set import (
    PublishRuleVersion,
    RuleMutationCommand,
    RuleOperationStatus,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.domain.registered_sources import (
    SourceAuthenticationMode,
)
from atlas_richie.sentinel_console.domain.rule_bindings import RuleKind
from atlas_richie.sentinel_console.domain.rule_candidates import candidate_checksum
from atlas_richie.sentinel_console.domain.rule_publication_targets import (
    ConsulRulePublicationTarget,
    NacosRulePublicationTarget,
)
from atlas_richie.sentinel_console.domain.rule_snapshots import RuleRecord
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_reader import (
    ConsulRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.consul_rule_source_writer import (
    ConsulRuleSourceWrite,
    ConsulRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.nacos_grpc_transport import (
    NacosGrpcTlsCredentials,
    NacosGrpcTransport,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_reader import (
    NacosRuleSourceReader,
)
from atlas_richie.sentinel_console.infrastructure.nacos_rule_source_writer import (
    NacosRuleSourceWrite,
    NacosRuleSourceWriter,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AuthenticationSessionRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleMutationOperationRecord,
    RulePublicationRecord,
    RulePublicationTargetRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.registered_source_store import (
    encrypt_registered_source_credentials,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_binding_directory_reader import (
    SqlAlchemyRuleBindingDirectoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_mutation_composition import (
    create_sql_rule_mutation_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_target_mapping import (
    target_body,
    target_location,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_version_reader import (
    SqlAlchemyRuleVersionReader,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)
from atlas_richie.sentinel_console.infrastructure.security.rule_command_keys import (
    RuleCommandKeyConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)
from atlas_richie.sentinel_console.infrastructure.sentinel_rule_version_encoder import (
    SentinelRuleVersionJsonEncoder,
)

_NACOS_IMAGE = "nacos/nacos-server:v3.2.4"
_DUAL_ACCEPTANCE_ENV = "SENTINEL_CONSOLE_RUN_DUAL_PROVIDER_CLI_ACCEPTANCE"
_AUTHENTICATED_DUAL_ACCEPTANCE_ENV = (
    "SENTINEL_CONSOLE_RUN_AUTHENTICATED_DUAL_PROVIDER_CLI_ACCEPTANCE"
)
_DUAL_PROVIDER_FAILURE_ACCEPTANCE_ENV = (
    "SENTINEL_CONSOLE_RUN_DUAL_PROVIDER_FAILURE_ACCEPTANCE"
)


class InstalledCliDualProviderAcceptanceTests(unittest.TestCase):
    """Verify the installed CLI worker routes durable work to both providers."""

    def test_installed_cli_publishes_sql_outbox_to_nacos_and_consul(self) -> None:
        if os.environ.get(_DUAL_ACCEPTANCE_ENV) != "1":
            self.skipTest(f"set {_DUAL_ACCEPTANCE_ENV}=1 to enable Docker acceptance")
        database_url = os.environ.get(bootstrap_acceptance._RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_e2e_dependencies.sh")
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        self._run_dual_provider_acceptance(database_url, "mysql")

    def test_installed_cli_postgresql_publishes_sql_outbox_to_nacos_and_consul(
        self,
    ) -> None:
        if os.environ.get(_DUAL_ACCEPTANCE_ENV) != "1":
            self.skipTest(f"set {_DUAL_ACCEPTANCE_ENV}=1 to enable Docker acceptance")
        database_url = os.environ.get(bootstrap_acceptance._RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_postgresql_acceptance.sh")
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        self._run_dual_provider_acceptance(database_url, "postgresql")

    def test_installed_cli_publishes_authenticated_dual_provider_sql_outbox(
        self,
    ) -> None:
        if os.environ.get(_AUTHENTICATED_DUAL_ACCEPTANCE_ENV) != "1":
            self.skipTest(
                f"set {_AUTHENTICATED_DUAL_ACCEPTANCE_ENV}=1 to enable Docker acceptance"
            )
        database_url = os.environ.get(bootstrap_acceptance._RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_e2e_dependencies.sh")
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        asyncio.run(
            self._run_authenticated_dual_provider_acceptance(database_url, "mysql")
        )

    def test_installed_cli_postgresql_publishes_authenticated_dual_provider_sql_outbox(
        self,
    ) -> None:
        if os.environ.get(_AUTHENTICATED_DUAL_ACCEPTANCE_ENV) != "1":
            self.skipTest(
                f"set {_AUTHENTICATED_DUAL_ACCEPTANCE_ENV}=1 to enable Docker acceptance"
            )
        database_url = os.environ.get(bootstrap_acceptance._RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_postgresql_acceptance.sh")
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        asyncio.run(
            self._run_authenticated_dual_provider_acceptance(database_url, "postgresql")
        )

    def test_installed_cli_isolates_consul_failure_from_nacos_publication(self) -> None:
        if os.environ.get(_DUAL_PROVIDER_FAILURE_ACCEPTANCE_ENV) != "1":
            self.skipTest(
                f"set {_DUAL_PROVIDER_FAILURE_ACCEPTANCE_ENV}=1 to enable Docker acceptance"
            )
        database_url = os.environ.get(bootstrap_acceptance._RUN_MYSQL_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_e2e_dependencies.sh")
        self.assertTrue(database_url.startswith("mysql+asyncmy://"))
        asyncio.run(
            self._run_authenticated_dual_provider_acceptance(
                database_url, "mysql", verify_consul_failure_isolation=True
            )
        )

    def test_installed_cli_postgresql_isolates_consul_failure_from_nacos_publication(
        self,
    ) -> None:
        if os.environ.get(_DUAL_PROVIDER_FAILURE_ACCEPTANCE_ENV) != "1":
            self.skipTest(
                f"set {_DUAL_PROVIDER_FAILURE_ACCEPTANCE_ENV}=1 to enable Docker acceptance"
            )
        database_url = os.environ.get(bootstrap_acceptance._RUN_POSTGRES_URL_ENV)
        if not database_url:
            self.skipTest("run through with_disposable_postgresql_acceptance.sh")
        self.assertTrue(database_url.startswith("postgresql+psycopg://"))
        asyncio.run(
            self._run_authenticated_dual_provider_acceptance(
                database_url, "postgresql", verify_consul_failure_isolation=True
            )
        )

    async def _run_authenticated_dual_provider_acceptance(
        self,
        database_url: str,
        database_kind: str,
        *,
        verify_consul_failure_isolation: bool = False,
    ) -> None:
        """Exercise installed workers with both real provider auth paths enabled."""
        token = uuid4().hex
        consul_key = f"sentinel/cli-dual-auth/{token}/rules.json"
        nacos = nacos_auth_acceptance.NacosRegisteredSourceAuthAcceptance()
        consul = DisposableConsulAclServer(consul_key)
        temporary_ca_bundle: tempfile.TemporaryDirectory[str] | None = None
        try:
            await nacos.asyncSetUp()
            await consul.start()
            certificate_path = (
                Path(nacos._certificate_directory.name) / "certificate.pem"
            )
            temporary_ca_bundle = tempfile.TemporaryDirectory(
                prefix="sentinel-dual-provider-ca-"
            )
            ca_bundle_path = Path(temporary_ca_bundle.name) / "providers-ca.pem"
            ca_bundle_path.write_text(
                f"{certificate_path.read_text(encoding='utf-8').rstrip()}\n"
                f"{Path(consul._certificate_directory.name, 'certificate.pem').read_text(encoding='utf-8').rstrip()}\n",
                encoding="utf-8",
            )
            nacos_port = nacos._proxy_port
            nacos_grpc_port = nacos._grpc_proxy_port
            provider_targets = (
                f"nacos|127.0.0.1|127.0.0.1/32|{nacos_port},{nacos_grpc_port};"
                f"consul|127.0.0.1|127.0.0.1/32|{consul.proxy_port}"
            )
            endpoint = f"https://127.0.0.1:{nacos_port}/nacos"
            environment = {
                "SENTINEL_E2E_CONSUL_URL": consul.endpoint,
                "SENTINEL_E2E_CONSUL_TOKEN": consul.application_token,
                "SENTINEL_CONSOLE_TEST_NACOS_HTTP_PORT": str(nacos_port),
                "SENTINEL_CONSOLE_TEST_NACOS_GRPC_PORT": str(nacos_grpc_port),
            }
            service_environment_overrides = {
                "SENTINEL_CONSOLE_REGISTERED_SOURCE_TARGETS": provider_targets,
                "SENTINEL_CONSOLE_REGISTERED_SOURCE_ROOT_CERTIFICATE": str(
                    ca_bundle_path
                ),
                "SENTINEL_CONSOLE_NACOS_GRPC_ROOT_CERTIFICATE": str(certificate_path),
            }

            def verify_publication(
                _port: int,
                runtime_directory: Path,
                service_environment: dict[str, str],
            ) -> None:
                self._run_publication_acceptance(
                    database_url=database_url,
                    service_environment=service_environment,
                    nacos_http_port=nacos_port,
                    nacos_grpc_port=nacos_grpc_port,
                    nacos_password=nacos_auth_acceptance._ADMIN_PASSWORD,
                    consul_token=consul.application_token,
                    consul_key=consul_key,
                    tls_ca_bundle=ca_bundle_path,
                    nacos_grpc_root_certificate=certificate_path,
                    consul_fault=consul if verify_consul_failure_isolation else None,
                )
                service_log = (runtime_directory / "console.log").read_text(
                    errors="replace"
                )
                if any(
                    secret in service_log
                    for secret in (
                        nacos_auth_acceptance._ADMIN_PASSWORD,
                        consul.application_token,
                    )
                ):
                    raise AssertionError("provider credential appeared in CLI log")

            with patch.dict(os.environ, environment):
                await asyncio.to_thread(
                    bootstrap_acceptance.InstalledCliBootstrapAcceptanceTests()._run_installed_cli_acceptance,
                    database_url,
                    database_kind,
                    enable_dual_provider_publication=True,
                    initial_source={
                        "provider": "nacos",
                        "endpoint": endpoint,
                        "namespace": "public",
                        "authentication": {
                            "mode": "direct",
                            "username": "nacos",
                            "password": nacos_auth_acceptance._ADMIN_PASSWORD,
                        },
                    },
                    service_environment_overrides=service_environment_overrides,
                    expected_source_secret=nacos_auth_acceptance._ADMIN_PASSWORD,
                    after_initialize=verify_publication,
                )
            if not consul.observed_requests:
                raise AssertionError(
                    "authenticated Consul provider received no requests"
                )
            if any(
                request_token != consul.application_token
                or consul.application_token in request_path
                for request_path, request_token in consul.observed_requests
            ):
                raise AssertionError(
                    "Consul publication did not keep the ACL token in the authenticated header"
                )
        finally:
            if temporary_ca_bundle is not None:
                temporary_ca_bundle.cleanup()
            await consul.close()
            await nacos.asyncTearDown()

    def _run_dual_provider_acceptance(
        self, database_url: str, database_kind: str
    ) -> None:
        if shutil.which("docker") is None:
            self.skipTest("Docker is required for disposable Nacos")
        docker = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if docker.returncode != 0:
            self.skipTest("Docker daemon is unavailable")

        run_id = uuid4().hex
        http_port, grpc_port = _free_loopback_port_pair()
        container_name = f"sentinel-cli-dual-nacos-{run_id[:12]}"
        container_id: str | None = None
        try:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--rm",
                    "--name",
                    container_name,
                    "--label",
                    f"{_CONTAINER_OWNER_LABEL}={run_id}",
                    "--env",
                    "MODE=standalone",
                    "--env",
                    "NACOS_AUTH_ENABLE=false",
                    "--env",
                    "NACOS_AUTH_ADMIN_ENABLE=false",
                    "--env",
                    "NACOS_AUTH_CONSOLE_ENABLE=false",
                    "--env",
                    "NACOS_AUTH_TOKEN=sentinel-disposable-nacos-auth-token-0123456789abcdef",
                    "--env",
                    "NACOS_AUTH_IDENTITY_KEY=sentinel-local-test",
                    "--env",
                    "NACOS_AUTH_IDENTITY_VALUE=sentinel-local-test-only",
                    "--publish",
                    f"127.0.0.1:{http_port}:8848/tcp",
                    "--publish",
                    f"127.0.0.1:{grpc_port}:9848/tcp",
                    _NACOS_IMAGE,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            container_id = result.stdout.strip()
            self.assertEqual(len(container_id), 64)
            endpoint = f"http://127.0.0.1:{http_port}/nacos"
            _wait_for_nacos(endpoint)

            environment = {
                "SENTINEL_CONSOLE_TEST_NACOS_HTTP_PORT": str(http_port),
                "SENTINEL_CONSOLE_TEST_NACOS_GRPC_PORT": str(grpc_port),
            }
            with patch.dict(os.environ, environment):
                bootstrap_acceptance.InstalledCliBootstrapAcceptanceTests()._run_installed_cli_acceptance(
                    database_url,
                    database_kind,
                    enable_dual_provider_publication=True,
                    after_initialize=lambda _port, _directory, service_environment: (
                        self._run_publication_acceptance(
                            database_url=database_url,
                            service_environment=service_environment,
                            nacos_http_port=http_port,
                            nacos_grpc_port=grpc_port,
                        )
                    ),
                )
        finally:
            if container_id is not None:
                _remove_owned_container(container_id, run_id)

    def _run_publication_acceptance(
        self,
        *,
        database_url: str,
        service_environment: dict[str, str],
        nacos_http_port: int,
        nacos_grpc_port: int,
        nacos_password: str | None = None,
        consul_token: str | None = None,
        consul_key: str | None = None,
        tls_ca_bundle: Path | None = None,
        nacos_grpc_root_certificate: Path | None = None,
        consul_fault: DisposableConsulAclServer | None = None,
    ) -> None:
        asyncio.run(
            _publish_from_installed_cli_worker(
                database_url=database_url,
                service_environment=service_environment,
                nacos_http_port=nacos_http_port,
                nacos_grpc_port=nacos_grpc_port,
                nacos_password=nacos_password,
                consul_token=consul_token,
                consul_key=consul_key,
                tls_ca_bundle=tls_ca_bundle,
                nacos_grpc_root_certificate=nacos_grpc_root_certificate,
                consul_fault=consul_fault,
            )
        )


async def _publish_from_installed_cli_worker(
    *,
    database_url: str,
    service_environment: dict[str, str],
    nacos_http_port: int,
    nacos_grpc_port: int,
    nacos_password: str | None = None,
    consul_token: str | None = None,
    consul_key: str | None = None,
    tls_ca_bundle: Path | None = None,
    nacos_grpc_root_certificate: Path | None = None,
    consul_fault: DisposableConsulAclServer | None = None,
) -> None:
    """Seed valid commands, then observe the running installed CLI workers."""
    token = uuid4().hex
    now = datetime.now(UTC).replace(microsecond=0)
    account_id, session_digest, csrf_digest = await _seed_dual_provider_authority(
        database_url, token=token, now=now
    )
    consul_url = service_environment["SENTINEL_E2E_CONSUL_URL"]
    consul_port = urlsplit(consul_url).port
    if consul_port is None:
        raise AssertionError("disposable Consul URL must include an explicit port")
    nacos_scheme = "https" if nacos_password is not None else "http"
    nacos_url = f"{nacos_scheme}://127.0.0.1:{nacos_http_port}/nacos"
    nacos_source_revision = f"source-revision-nacos-{token}"
    if nacos_password is None:
        nacos_source_id = f"source-nacos-{token}"
    else:
        source_engine = create_async_engine(database_url, hide_parameters=True)
        try:
            async with source_engine.connect() as connection:
                registered_nacos = (
                    await connection.execute(
                        select(
                            RegisteredConfigurationSourceRecord.source_id,
                            RegisteredConfigurationSourceRecord.revision,
                        ).where(
                            RegisteredConfigurationSourceRecord.provider
                            == ConfigurationSourceProvider.NACOS.value
                        )
                    )
                ).all()
        finally:
            await source_engine.dispose()
        if len(registered_nacos) != 1:
            raise AssertionError(
                "installed setup must register exactly one authenticated Nacos source"
            )
        nacos_source_id, nacos_source_revision = registered_nacos[0]
    consul_source_id = f"source-consul-{token}"
    consul_source_revision = f"source-revision-consul-{token}"
    nacos_binding_id = f"binding-nacos-{token}"
    consul_binding_id = f"binding-consul-{token}"
    nacos_target = NacosRulePublicationTarget(
        binding_id=nacos_binding_id,
        source_id=nacos_source_id,
        namespace="public",
        group=_GROUP,
        data_id=f"cli-dual-{token}.json",
    )
    consul_target = ConsulRulePublicationTarget(
        binding_id=consul_binding_id,
        source_id=consul_source_id,
        datacenter="dc1",
        key=consul_key or f"sentinel/cli-dual/{token}/rules.json",
    )
    nacos_connection = SourceConnectionInput(
        source_id=nacos_source_id,
        expected_revision=nacos_source_revision,
        provider=ConfigurationSourceProvider.NACOS,
        endpoint=nacos_url,
        location="public",
        authentication_mode=(
            SourceCheckAuthenticationMode.DIRECT
            if nacos_password is not None
            else SourceCheckAuthenticationMode.NONE
        ),
        username="nacos" if nacos_password is not None else None,
        password=nacos_password,
    )
    consul_connection = SourceConnectionInput(
        source_id=consul_source_id,
        expected_revision=consul_source_revision,
        provider=ConfigurationSourceProvider.CONSUL,
        endpoint=consul_url,
        location="dc1",
        authentication_mode=(
            SourceCheckAuthenticationMode.DIRECT
            if consul_token is not None
            else SourceCheckAuthenticationMode.NONE
        ),
        acl_token=consul_token,
    )
    tls_context = (
        ssl.create_default_context(cafile=str(tls_ca_bundle))
        if tls_ca_bundle is not None
        else None
    )
    grpc_tls_credentials = (
        NacosGrpcTlsCredentials(
            root_certificates=nacos_grpc_root_certificate.read_bytes()
        )
        if nacos_grpc_root_certificate is not None
        else None
    )
    engine = create_async_engine(database_url, hide_parameters=True)
    request_keys = (f"cli-nacos-{token}", f"cli-consul-{token}")
    nacos_version_during_consul_failure: str | None = None
    try:
        policy = _provider_policy(
            nacos_http_port=nacos_http_port,
            nacos_grpc_port=nacos_grpc_port,
            consul_port=consul_port,
        )
        http_client = PinnedAioHttpJsonClient(ssl_context=tls_context)
        baseline_consul_cas_count = (
            _consul_candidate_cas_count(consul_fault, consul_target.key)
            if consul_fault is not None
            else 0
        )
        expected = await _seed_targets_versions_and_operations(
            engine,
            token=token,
            now=now,
            account_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            nacos_target=nacos_target,
            consul_target=consul_target,
            nacos_http_port=nacos_http_port,
            nacos_grpc_port=nacos_grpc_port,
            nacos_connection=nacos_connection,
            consul_connection=consul_connection,
            preexisting_source_ids=frozenset(
                {nacos_source_id} if nacos_password is not None else set()
            ),
            tls_context=tls_context,
            grpc_tls_credentials=grpc_tls_credentials,
            request_keys=request_keys,
            consul_fault=consul_fault,
        )
        if consul_fault is not None:
            # Fail only Consul's first candidate CAS, after the local proxy has
            # received it but before the real provider can commit it. Hold the
            # later, authorized recovery CAS so both provider states can be
            # inspected while the installed CLI workers are still running.
            await consul_fault.wait_for_pre_upstream_cas_drop(timeout=45)
            consul_fault.arm_hold_cas_before_upstream(consul_target.key)
            await consul_fault.wait_for_held_cas(timeout=45)

            (
                pending_nacos,
                pending_consul,
                consul_publication,
            ) = await _read_dual_provider_operation_states(
                engine,
                request_keys=request_keys,
                consul_binding_id=consul_target.binding_id,
            )
            if (
                pending_nacos.status != RuleOperationStatus.COMPLETED.value
                or pending_nacos.work_attempt_count != 1
            ):
                raise AssertionError(
                    "Nacos publication did not complete exactly once while Consul recovery was held"
                )
            if pending_consul.status != RuleOperationStatus.PENDING.value:
                raise AssertionError(
                    "Consul operation must remain pending while its recovery CAS is held"
                )
            if consul_publication.write_state != "unknown":
                raise AssertionError(
                    "Consul must retain its unknown write fact until recovery CAS completes"
                )
            if (
                _consul_candidate_cas_count(consul_fault, consul_target.key)
                != baseline_consul_cas_count + 2
            ):
                raise AssertionError(
                    "Consul must show one dropped candidate CAS and one held recovery CAS"
                )

            nacos_snapshot_during_consul_failure = await NacosRuleSourceReader(
                policy, http_client=http_client
            ).read(nacos_connection, nacos_target)
            consul_snapshot_before_recovery = await ConsulRuleSourceReader(
                policy, http_client=http_client
            ).read(consul_connection, consul_target.key)
            if nacos_snapshot_during_consul_failure.value != expected["nacos"]:
                raise AssertionError(
                    "Nacos candidate was not committed while Consul was unavailable"
                )
            nacos_version_during_consul_failure = (
                nacos_snapshot_during_consul_failure.md5
            )
            if consul_snapshot_before_recovery.value == expected["consul"]:
                raise AssertionError(
                    "Consul candidate reached the provider despite the pre-upstream fault"
                )

            consul_fault.release_held_cas()
        await _wait_for_installed_cli_operations(engine, request_keys)
        nacos_snapshot = await NacosRuleSourceReader(
            policy, http_client=http_client
        ).read(nacos_connection, nacos_target)
        consul_snapshot = await ConsulRuleSourceReader(
            policy, http_client=http_client
        ).read(consul_connection, consul_target.key)
        if nacos_snapshot.value != expected["nacos"]:
            raise AssertionError("installed worker did not read back exact Nacos bytes")
        if consul_snapshot.value != expected["consul"]:
            raise AssertionError(
                "installed worker did not read back exact Consul bytes"
            )
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    select(
                        RulePublicationRecord.binding_id,
                        RulePublicationRecord.write_state,
                        RulePublicationRecord.read_back_state,
                    ).where(
                        RulePublicationRecord.binding_id.in_(
                            (nacos_target.binding_id, consul_target.binding_id)
                        )
                    )
                )
            ).all()
            operations = (
                await connection.execute(
                    select(
                        RuleMutationOperationRecord.request_key,
                        RuleMutationOperationRecord.status,
                        RuleMutationOperationRecord.work_attempt_count,
                    ).where(RuleMutationOperationRecord.request_key.in_(request_keys))
                )
            ).all()
        if len(rows) != 2 or any(
            row.write_state != "succeeded" or row.read_back_state != "succeeded"
            for row in rows
        ):
            raise AssertionError(
                "dual-provider SQL publication receipts are incomplete"
            )
        if len(operations) != 2 or any(
            row.status != RuleOperationStatus.COMPLETED.value
            or row.work_attempt_count < 1
            for row in operations
        ):
            raise AssertionError("dual-provider outbox operations did not complete")
        if consul_fault is not None:
            (
                final_nacos_operation,
                _final_consul_operation,
                _publication,
            ) = await _read_dual_provider_operation_states(
                engine,
                request_keys=request_keys,
                consul_binding_id=consul_target.binding_id,
            )
            if final_nacos_operation.work_attempt_count != 1:
                raise AssertionError(
                    "Nacos operation was reclaimed after its successful publication"
                )
            if nacos_snapshot.md5 != nacos_version_during_consul_failure:
                raise AssertionError(
                    "Nacos configuration revision changed during Consul recovery"
                )
            if _consul_candidate_cas_count(consul_fault, consul_target.key) != (
                baseline_consul_cas_count + 2
            ):
                raise AssertionError(
                    "Consul recovery issued an unexpected extra candidate CAS"
                )
    finally:
        if consul_fault is not None:
            consul_fault.release_held_cas()
        await engine.dispose()


async def _seed_dual_provider_authority(
    database_url: str, *, token: str, now: datetime
) -> tuple[str, str, str]:
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            account_id = await connection.scalar(
                select(AccountRecord.account_id).where(
                    AccountRecord.username
                    == bootstrap_acceptance._INSTALLED_ADMIN_USERNAME
                )
            )
        if account_id is None:
            raise AssertionError("installed first-run admin was not persisted")
        session_digest = hashlib.sha256(f"session-{token}".encode()).hexdigest()
        csrf_digest = hashlib.sha256(f"csrf-{token}".encode()).hexdigest()
        async with engine.begin() as connection:
            await connection.execute(
                insert(AuthenticationSessionRecord).values(
                    session_hash=session_digest,
                    account_id=account_id,
                    session_epoch=token[:36],
                    csrf_hash=csrf_digest,
                    created_at=now,
                    expires_at=now + timedelta(hours=1),
                    revoked_at=None,
                )
            )
        return account_id, session_digest, csrf_digest
    finally:
        await engine.dispose()


async def _write_provider_baselines(
    *,
    nacos_connection: SourceConnectionInput,
    consul_connection: SourceConnectionInput,
    nacos_http_port: int,
    nacos_grpc_port: int,
    nacos_target: NacosRulePublicationTarget,
    consul_target: ConsulRulePublicationTarget,
    nacos_value: bytes,
    consul_value: bytes,
    tls_context: ssl.SSLContext | None,
    grpc_tls_credentials: NacosGrpcTlsCredentials | None,
) -> tuple[str, str]:
    policy = _provider_policy(
        nacos_http_port=nacos_http_port,
        nacos_grpc_port=nacos_grpc_port,
        consul_port=urlsplit(consul_connection.endpoint).port or 0,
    )
    http_client = PinnedAioHttpJsonClient(ssl_context=tls_context)
    nacos_reader = NacosRuleSourceReader(policy, http_client=http_client)
    nacos_writer = NacosRuleSourceWriter(
        policy,
        nacos_reader,
        http_client=http_client,
        grpc_client=NacosGrpcTransport(grpc_tls_credentials),
    )
    consul_writer = ConsulRuleSourceWriter(policy, http_client=http_client)
    nacos_baseline = await nacos_writer.write(
        NacosRuleSourceWrite(nacos_connection, nacos_target, None, nacos_value)
    )
    consul_baseline = await consul_writer.write(
        ConsulRuleSourceWrite(consul_connection, consul_target.key, None, consul_value)
    )
    return nacos_baseline.md5, consul_baseline.modify_index


async def _seed_targets_versions_and_operations(
    engine,
    *,
    token: str,
    now: datetime,
    account_id: str,
    session_digest: str,
    csrf_digest: str,
    nacos_target: NacosRulePublicationTarget,
    consul_target: ConsulRulePublicationTarget,
    nacos_http_port: int,
    nacos_grpc_port: int,
    nacos_connection: SourceConnectionInput,
    consul_connection: SourceConnectionInput,
    preexisting_source_ids: frozenset[str],
    tls_context: ssl.SSLContext | None,
    grpc_tls_credentials: NacosGrpcTlsCredentials | None,
    request_keys: tuple[str, str],
    consul_fault: DisposableConsulAclServer | None = None,
) -> dict[str, bytes]:
    targets = (
        (
            ConfigurationSourceProvider.NACOS,
            nacos_target,
            nacos_connection.expected_revision,
        ),
        (
            ConfigurationSourceProvider.CONSUL,
            consul_target,
            consul_connection.expected_revision,
        ),
    )
    baseline_candidates = {
        target.binding_id: _candidate(target.binding_id, count=5)
        for _provider, target, _revision in targets
    }
    baseline_version_ids = {
        target.binding_id: f"baseline-{provider.value}-{token}"
        for provider, target, _revision in targets
    }
    baseline_validation_ids = {
        target.binding_id: f"baseline-validation-{provider.value}-{token}"
        for provider, target, _revision in targets
    }
    baseline_checksums = {
        binding_id: candidate_checksum(candidate)
        for binding_id, candidate in baseline_candidates.items()
    }
    candidates = {
        target.binding_id: replace(
            _candidate(target.binding_id),
            base_version_id=baseline_version_ids[target.binding_id],
            base_checksum=baseline_checksums[target.binding_id],
        )
        for _provider, target, _revision in targets
    }
    versions = {
        target.binding_id: (
            f"version-{provider.value}-{token}",
            f"validation-{provider.value}-{token}",
        )
        for provider, target, _revision in targets
    }
    async with engine.begin() as connection:
        for provider, target, source_revision in targets:
            source_id = target.source_id
            source_connection = (
                nacos_connection
                if provider is ConfigurationSourceProvider.NACOS
                else consul_connection
            )
            location = (
                "public" if provider is ConfigurationSourceProvider.NACOS else "dc1"
            )
            if source_id not in preexisting_source_ids:
                encrypted_credentials = encrypt_registered_source_credentials(
                    source_connection,
                    source_id,
                    AesGcmSecretCipher(
                        "source-secret-v1", {"source-secret-v1": b"s" * 32}
                    ),
                )
                authentication_mode = (
                    SourceAuthenticationMode.DIRECT.value
                    if encrypted_credentials is not None
                    else SourceAuthenticationMode.NONE.value
                )
                await connection.execute(
                    insert(RegisteredConfigurationSourceRecord).values(
                        source_id=source_id,
                        revision=source_revision,
                        name=f"Disposable {provider.value} {token[:8]}",
                        endpoint=source_connection.endpoint,
                        provider=provider.value,
                        location=location,
                        authentication_mode=authentication_mode,
                        credential_configured=encrypted_credentials is not None,
                        credential_cipher_format=(
                            encrypted_credentials.format.value
                            if encrypted_credentials is not None
                            else None
                        ),
                        credential_key_id=(
                            encrypted_credentials.key_id
                            if encrypted_credentials is not None
                            else None
                        ),
                        credential_payload=(
                            encrypted_credentials.payload
                            if encrypted_credentials is not None
                            else None
                        ),
                        created_at=now,
                        updated_at=now,
                        updated_by_account_id=account_id,
                    )
                )
                if source_connection.acl_token is not None and (
                    encrypted_credentials is None
                    or source_connection.acl_token.encode("utf-8")
                    in encrypted_credentials.payload
                ):
                    raise AssertionError(
                        "Consul ACL token was not stored as SQL ciphertext"
                    )
            candidate = candidates[target.binding_id]
            checksum = candidate_checksum(candidate)
            version_id, validation_id = versions[target.binding_id]
            baseline_candidate = baseline_candidates[target.binding_id]
            baseline_checksum = baseline_checksums[target.binding_id]
            baseline_version_id = baseline_version_ids[target.binding_id]
            baseline_validation_id = baseline_validation_ids[target.binding_id]
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=baseline_validation_id,
                    binding_id=target.binding_id,
                    profile=_PROFILE,
                    base_checksum=baseline_candidate.base_checksum,
                    candidate_checksum=baseline_checksum,
                    is_publishable=True,
                    issues=[],
                    actor_account_id=account_id,
                    request_id=f"baseline-validation-{token}-{provider.value}",
                    created_at=now,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id=baseline_version_id,
                    binding_id=target.binding_id,
                    kind=baseline_candidate.kind.value,
                    profile=_PROFILE,
                    base_version_id=baseline_candidate.base_version_id,
                    checksum=baseline_checksum,
                    name=f"Installed CLI baseline {provider.value}",
                    note="",
                    validation_id=baseline_validation_id,
                    records=[
                        rule_record_body(
                            RuleRecord(
                                "acceptance-record", baseline_candidate.rules[0].rule
                            )
                        )
                    ],
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )
            await connection.execute(
                insert(RuleBindingRecord).values(
                    binding_id=target.binding_id,
                    environment_id="acceptance",
                    app_id=f"installed-cli-dual-{provider.value}",
                    kind=RuleKind.FLOW.value,
                    profile=_PROFILE,
                    source_id=source_id,
                    location=target_location(target),
                    created_at=now,
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RulePublicationTargetRecord).values(
                    binding_id=target.binding_id,
                    source_id=source_id,
                    target_revision=f"target-revision-{token}",
                    source_revision=source_revision,
                    target_body=target_body(target),
                    updated_at=now,
                )
            )
            await connection.execute(
                insert(RuleValidationReceiptRecord).values(
                    validation_id=validation_id,
                    binding_id=target.binding_id,
                    profile=_PROFILE,
                    base_checksum=candidate.base_checksum,
                    candidate_checksum=checksum,
                    is_publishable=True,
                    issues=[],
                    actor_account_id=account_id,
                    request_id=f"validation-{token}-{provider.value}",
                    created_at=now,
                )
            )
            await connection.execute(
                insert(RuleSetVersionRecord).values(
                    version_id=version_id,
                    binding_id=target.binding_id,
                    kind=candidate.kind.value,
                    profile=_PROFILE,
                    base_version_id=candidate.base_version_id,
                    checksum=checksum,
                    name=f"Installed CLI {provider.value} acceptance",
                    note="",
                    validation_id=validation_id,
                    records=[
                        rule_record_body(
                            RuleRecord("acceptance-record", candidate.rules[0].rule)
                        )
                    ],
                    created_at=now,
                    created_by_account_id=account_id,
                )
            )

    version_reader = SqlAlchemyRuleVersionReader(engine)
    encoder = SentinelRuleVersionJsonEncoder(_PROFILE)
    expected: dict[str, bytes] = {}
    baseline_values: dict[str, bytes] = {}
    for provider, target, _revision in targets:
        baseline = await version_reader.read_rule_version(
            target.binding_id, baseline_version_ids[target.binding_id]
        )
        version_id, _validation_id = versions[target.binding_id]
        version = await version_reader.read_rule_version(target.binding_id, version_id)
        if baseline is None or version is None:
            raise AssertionError(f"missing seeded {provider.value} rule version")
        baseline_values[provider.value] = encoder.encode_rule_version(baseline)
        expected[provider.value] = encoder.encode_rule_version(version)

    nacos_expected_revision, consul_expected_revision = await _write_provider_baselines(
        nacos_connection=nacos_connection,
        consul_connection=consul_connection,
        nacos_http_port=nacos_http_port,
        nacos_grpc_port=nacos_grpc_port,
        nacos_target=nacos_target,
        consul_target=consul_target,
        nacos_value=baseline_values["nacos"],
        consul_value=baseline_values["consul"],
        tls_context=tls_context,
        grpc_tls_credentials=grpc_tls_credentials,
    )
    if consul_fault is not None:
        # Baseline creation uses cas=0. Arm only after it, before outbox rows
        # become visible to the installed CLI workers.
        consul_fault.arm_cas_drop_before_upstream(consul_target.key)

    store = create_sql_rule_mutation_store(
        engine,
        RuleCommandKeyConfiguration("acceptance-v1", {"acceptance-v1": b"q" * 32}),
        binding_reader=SqlAlchemyRuleBindingDirectoryReader(engine),
    )
    for (provider, target, _source_revision), request_key, expected_revision in zip(
        targets,
        request_keys,
        (nacos_expected_revision, consul_expected_revision),
        strict=True,
    ):
        version_id, _validation_id = versions[target.binding_id]
        candidate = candidates[target.binding_id]
        operation = await store.mutate(
            RuleMutationCommand(
                target.binding_id,
                request_key,
                PublishRuleVersion(
                    version_id=version_id,
                    version_checksum=candidate_checksum(candidate),
                    expected_version_id=baseline_version_ids[target.binding_id],
                    expected_checksum="sha256:" + hashlib.sha256(
                        baseline_values[provider.value]
                    ).hexdigest(),
                    expected_source_revision=expected_revision,
                    reason=f"installed CLI dual provider {provider.value}",
                ),
            ),
            actor_id=account_id,
            session_digest=session_digest,
            csrf_digest=csrf_digest,
            request_id=f"dual-provider-{token}-{provider.value}",
            now=now,
        )
        if operation.status is not RuleOperationStatus.PENDING:
            raise AssertionError(f"{provider.value} publish was not accepted")
    return expected


async def _wait_for_installed_cli_operations(
    engine, request_keys: tuple[str, str]
) -> None:
    deadline = asyncio.get_running_loop().time() + 150
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as connection:
            statuses = (
                await connection.execute(
                    select(
                        RuleMutationOperationRecord.request_key,
                        RuleMutationOperationRecord.status,
                        RuleMutationOperationRecord.work_attempt_count,
                        RuleMutationOperationRecord.reason,
                        RuleMutationOperationRecord.work_lease_expires_at,
                    ).where(RuleMutationOperationRecord.request_key.in_(request_keys))
                )
            ).all()
        if len(statuses) == 2 and all(
            status == RuleOperationStatus.COMPLETED.value
            for _request_key, status, *_details in statuses
        ):
            return
        if any(
            status == RuleOperationStatus.REJECTED.value
            for _request_key, status, *_details in statuses
        ):
            raise AssertionError(
                "installed CLI rejected dual provider work: "
                f"operation_status={statuses!r}; "
                f"publication_status={await _read_publication_statuses(engine)!r}"
            )
        await asyncio.sleep(0.25)
    raise AssertionError(
        "installed CLI publication workers did not complete both providers; "
        f"operation_status={statuses!r}; "
        f"publication_status={await _read_publication_statuses(engine)!r}; "
        f"observed_at={datetime.now(UTC)!r}"
    )


async def _read_publication_statuses(engine) -> list[tuple[object, ...]]:
    async with engine.connect() as connection:
        return list(
            (
                await connection.execute(
                    select(
                        RulePublicationRecord.binding_id,
                        RulePublicationRecord.validation_state,
                        RulePublicationRecord.validation_reason,
                        RulePublicationRecord.write_state,
                        RulePublicationRecord.write_reason,
                        RulePublicationRecord.read_back_state,
                        RulePublicationRecord.read_back_reason,
                        RulePublicationRecord.validation_observed_at,
                        RulePublicationRecord.write_observed_at,
                        RulePublicationRecord.read_back_observed_at,
                    )
                )
            ).all()
        )


def _provider_policy(
    *, nacos_http_port: int, nacos_grpc_port: int, consul_port: int
) -> RegisteredSourceTargetPolicy:
    return RegisteredSourceTargetPolicy(
        (
            RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.NACOS,
                "127.0.0.1",
                ("127.0.0.1/32",),
                frozenset({nacos_http_port, nacos_grpc_port}),
            ),
            RegisteredSourceTargetRule.create(
                ConfigurationSourceProvider.CONSUL,
                "127.0.0.1",
                ("127.0.0.1/32",),
                frozenset({consul_port}),
            ),
        )
    )


async def _read_dual_provider_operation_states(
    engine,
    *,
    request_keys: tuple[str, str],
    consul_binding_id: str,
) -> tuple[object, object, object]:
    async with engine.connect() as connection:
        operations = (
            await connection.execute(
                select(
                    RuleMutationOperationRecord.request_key,
                    RuleMutationOperationRecord.status,
                    RuleMutationOperationRecord.work_attempt_count,
                ).where(RuleMutationOperationRecord.request_key.in_(request_keys))
            )
        ).all()
        publication = (
            await connection.execute(
                select(
                    RulePublicationRecord.write_state,
                    RulePublicationRecord.read_back_state,
                ).where(RulePublicationRecord.binding_id == consul_binding_id)
            )
        ).one_or_none()
    if len(operations) != 2 or publication is None:
        raise AssertionError("dual-provider SQL facts are incomplete")
    by_key = {row.request_key: row for row in operations}
    return by_key[request_keys[0]], by_key[request_keys[1]], publication


def _consul_candidate_cas_count(consul: DisposableConsulAclServer, key: str) -> int:
    """Count non-create CAS requests observed for the isolated test key."""
    expected_path = f"/v1/kv/{key}"
    return sum(
        1
        for raw_path, _token in consul.observed_requests
        if urlsplit(raw_path).path == expected_path
        and parse_qs(urlsplit(raw_path).query).get("cas") not in (None, ["0"])
    )
