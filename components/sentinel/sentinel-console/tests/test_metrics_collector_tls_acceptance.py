"""Loopback mTLS and durable receipt acceptance for the Metrics Collector."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
from anycorn import serve
from anycorn.config import Config
from atlas_richie.contracts.incidents.v1 import (
    IncidentSeverity,
    ResourcePressureMetric,
    encode_incident_event,
)
from atlas_richie.contracts.reporting.v2 import (
    HTTP_REQUEST_DURATION_BOUNDARIES_NS,
    CounterName,
    CounterReading,
    HistogramName,
    HistogramReading,
    MetricsSnapshot,
    decode_metrics_snapshot,
    encode_metrics_snapshot,
)
from atlas_richie.contracts.rules.load_observation.v1 import (
    RuleKind,
    RuleLoadEventKind,
    RuleLoadMemberFingerprint,
    RuleLoadObservationV1,
    RuleLoadSnapshotV1,
    encode_rule_load_observation,
)
from atlas_richie.sentinel.rules import (
    RuleRepository,
    RuleSnapshot,
    RuleTargetKind,
    RuleTargetProvenance,
    RuleVersion,
)
from atlas_richie.sentinel_reporter_incidents import (
    IncidentEventHttpTransport,
    IncidentEventProducer,
    IncidentEventReporter,
    IncidentReporterConfig,
    IncidentTlsCredential,
)
from atlas_richie.sentinel_reporter_rules import (
    RulePublicationReceiptHttpTransport,
    RulePublicationReceiptProducer,
    RulePublicationReceiptReporter,
    RulePublicationReceiptReporterConfig,
    RuleReceiptDeliveryCode,
    RuleReceiptDeliveryError,
    RuleReceiptTlsCredential,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsReporterBinding,
)
from atlas_richie.sentinel_console.application.read_rule_load_observations import (
    ReadRuleLoadObservations,
)
from atlas_richie.sentinel_console.application.run_rule_load_observation_projection_worker import (
    RunRuleLoadObservationProjectionWorker,
)
from atlas_richie.sentinel_console.application.run_rule_publication_receipt_projection_worker import (
    RunRulePublicationReceiptProjectionWorker,
)
from atlas_richie.sentinel_console.app import build_app
from atlas_richie.sentinel_console.domain.instance_catalog import (
    ObservationScope,
    ObservationWindow,
)
from atlas_richie.sentinel_console.domain.instance_observation import (
    MetricQuery,
    ObservationContext,
)
from atlas_richie.sentinel_console.domain.protocol_negotiations import (
    NegotiatedCompatibility,
)
from atlas_richie.sentinel_console.domain.session import ActiveAccountSession
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_collector_composition import (
    build_metrics_collector_app,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_history_reader import (
    SQLAlchemyMetricsHistoryReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.metrics_reporter_admin_composition import (
    build_metrics_reporter_admin,
)
from atlas_richie.sentinel_console.infrastructure.persistence.migration_runner import (
    upgrade_database,
)
from atlas_richie.sentinel_console.infrastructure.persistence.models import (
    AccountRecord,
    AgentReportingNegotiationRecord,
    IncidentEventNegotiationRecord,
    IncidentEventRecord,
    MetricsReporterBindingRecord,
    MetricsSnapshotRecord,
    RegisteredConfigurationSourceRecord,
    RuleBindingRecord,
    RuleLoadObservationInboxRecord,
    RuleLoadObservationNegotiationRecord,
    RuleLoadObservationOutboxRecord,
    RuleLoadObservationSequenceRecord,
    RulePublicationReceiptInboxRecord,
    RulePublicationReceiptOutboxRecord,
    RulePublicationRecord,
    RuleSetVersionRecord,
    RuleValidationReceiptRecord,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_projection_queue import (
    SqlAlchemyRuleLoadObservationProjectionQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_load_observation_reader import (
    SqlAlchemyRuleLoadObservationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_projection_queue import (
    SqlAlchemyRulePublicationReceiptProjectionQueue,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_receipt_store import (
    SqlAlchemyRulePublicationReceiptStore,
)
from atlas_richie.sentinel_console.infrastructure.persistence.rule_publication_reader import (
    SqlAlchemyRulePublicationReader,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_configuration import (
    RuntimeDatabaseLocatorConfiguration,
)
from atlas_richie.sentinel_console.infrastructure.persistence.runtime_database_locator_file_store import (
    RuntimeDatabaseLocatorFileStore,
)
from atlas_richie.sentinel_console.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
)

pytest.importorskip("anycorn")


class MetricsCollectorTlsAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rust_runtime_reads_disposable_consul_and_projects_real_collector_receipts(
        self,
    ) -> None:
        if (
            os.environ.get("SENTINEL_T005_RUST_CONSUL_ACCEPTANCE") != "true"
            or os.environ.get("SENTINEL_T005_RUST_CONSUL_DISPOSABLE") != "true"
        ):
            self.skipTest("run through the disposable Rust Consul acceptance wrapper")
        if shutil.which("docker") is None:
            self.skipTest("Rust runtime acceptance requires Docker")
        consul_url = os.environ.get("SENTINEL_T005_RUST_CONSUL_URL", "")
        parsed_consul = urlsplit(consul_url)
        if (
            parsed_consul.scheme != "http"
            or parsed_consul.hostname != "127.0.0.1"
            or parsed_consul.port is None
            or parsed_consul.path
            or parsed_consul.query
            or parsed_consul.fragment
        ):
            self.fail("Rust Consul acceptance requires its loopback disposable provider")

        with tempfile.TemporaryDirectory(
            prefix="sentinel-rust-runtime-consul-collector-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="host.docker.internal",
                is_ca=False,
                is_server=True,
                server_dns_name="host.docker.internal",
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="rust-consul-runtime-reporter",
                is_ca=False,
                is_server=False,
            )
            ca_path = root / "ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(_certificate_pem(reporter_certificate))
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))

            key = f"sentinel-t005/{uuid4().hex}/flow-rules.json"
            binding_id = f"rust-binding-{uuid4()}"
            publication_id = f"rust-publication-{uuid4()}"
            version_id = f"rust-version-{uuid4()}"
            source_id = f"rust-source-{uuid4()}"
            reporter_id = f"rust-reporter-{uuid4()}"
            principal = f"spiffe://sentinel.test/rust-consul-runtime/{uuid4()}"
            payload = (
                b'[{"resource":"sentinel-rust-demo-resource","grade":1,'
                b'"count":1,"strategy":0,"controlBehavior":0,'
                b'"limitApp":"default"}]'
            )
            payload_digest = hashlib.sha256(payload).hexdigest()
            envelope = json.dumps(
                {
                    "protocol_version": "atlas-richie.sentinel.managed-rule-publication/v1",
                    "binding_id": binding_id,
                    "publication_id": publication_id,
                    "target_version_id": version_id,
                    "publication_sequence": 1,
                    "rule_kind": "flow",
                    "profile_id": "sentinel-rust-v1",
                    "payload_sha256": payload_digest,
                    "rule_payload": payload.decode("utf-8"),
                },
                separators=(",", ":"),
            ).encode("utf-8")
            consul_key_url = f"{consul_url}/v1/kv/{key}"
            async with httpx.AsyncClient(timeout=5) as consul:
                published = await consul.put(consul_key_url, content=envelope)
                self.assertEqual(published.status_code, 200)
                self.assertIs(published.json(), True)

            database_url = _test_database_url(root)
            engine = create_async_engine(database_url)
            now = datetime.now(UTC).replace(microsecond=0)
            account_id = str(uuid4())
            try:
                await upgrade_database(engine)
                async with engine.begin() as connection:
                    await connection.execute(
                        insert(AccountRecord).values(
                            account_id=account_id,
                            username=f"rust-{uuid4().hex[:16]}",
                            username_key=uuid4().hex,
                            password_hash="$argon2id$acceptance-only",
                            role_id="admin",
                            status="active",
                            built_in=False,
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await connection.execute(
                        insert(RegisteredConfigurationSourceRecord).values(
                            source_id=source_id,
                            revision="source-revision-1",
                            name="Rust disposable Consul source",
                            endpoint=consul_url,
                            provider="consul",
                            location=key,
                            authentication_mode="none",
                            credential_configured=False,
                            created_at=now,
                            updated_at=now,
                            updated_by_account_id=account_id,
                        )
                    )
                    await connection.execute(
                        insert(RuleBindingRecord).values(
                            binding_id=binding_id,
                            environment_id="acceptance",
                            app_id="rust-consul-runtime",
                            kind="flow",
                            profile="sentinel-rust-v1",
                            source_id=source_id,
                            location=key,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    validation_id = f"rust-validation-{uuid4()}"
                    await connection.execute(
                        insert(RuleValidationReceiptRecord).values(
                            validation_id=validation_id,
                            binding_id=binding_id,
                            profile="sentinel-rust-v1",
                            base_checksum="base-checksum",
                            candidate_checksum="target-checksum",
                            is_publishable=True,
                            issues=[],
                            actor_account_id=account_id,
                            request_id=f"rust-request-{uuid4()}",
                            created_at=now,
                        )
                    )
                    await connection.execute(
                        insert(RuleSetVersionRecord).values(
                            version_id=version_id,
                            binding_id=binding_id,
                            kind="flow",
                            profile="sentinel-rust-v1",
                            base_version_id=None,
                            checksum="target-checksum",
                            name="Rust Consul acceptance target",
                            note="",
                            validation_id=validation_id,
                            records=[],
                            created_at=now,
                            created_by_account_id=account_id,
                        )
                    )
                    await connection.execute(
                        insert(RulePublicationRecord).values(
                            publication_id=publication_id,
                            binding_id=binding_id,
                            target_version_id=version_id,
                            target_checksum="target-checksum",
                            target_payload_checksum=payload_digest,
                            publication_sequence=1,
                            base_version_id=None,
                            created_at=now,
                            validation_state="succeeded",
                            validation_observed_at=now,
                            validation_reason=None,
                            write_state="succeeded",
                            write_observed_at=now,
                            write_reason=None,
                            read_back_state="succeeded",
                            read_back_observed_at=now,
                            read_back_reason=None,
                        )
                    )
                    await connection.execute(
                        insert(MetricsReporterBindingRecord).values(
                            certificate_principal=principal,
                            certificate_sha256=reporter_certificate.fingerprint(
                                hashes.SHA256()
                            ).hex(),
                            reporter_id=reporter_id,
                            environment_id="acceptance",
                            app_id="rust-consul-runtime",
                            instance_id=f"rust-instance-{uuid4()}",
                            process_id=f"rust-process-{uuid4()}",
                            revoked_at=None,
                            current_epoch=None,
                            last_sequence=0,
                            last_elapsed_ns=None,
                            last_received_at=None,
                        )
                    )
            except BaseException:
                await engine.dispose()
                raise

            collector_shutdown = asyncio.Event()
            collector_task: asyncio.Task[None] | None = None
            container_id: str | None = None
            owner = f"codex-t005-{uuid4().hex}"
            container_name = f"sentinel-t005-rust-{uuid4().hex[:12]}"
            repository_root = Path(__file__).resolve().parents[4]
            rust_project = repository_root / "components/sentinel/demos/rust-sentinel"
            try:
                locator_path = root / "runtime-locator.json"
                cipher = AesGcmSecretCipher(
                    "rust-runtime-test", {"rust-runtime-test": b"t" * 32}
                )
                await RuntimeDatabaseLocatorFileStore(locator_path, cipher).write(
                    database_url, expected_revision=None
                )
                locator_configuration = RuntimeDatabaseLocatorConfiguration(
                    locator_path,
                    "rust-runtime-test",
                    {"rust-runtime-test": b"t" * 32},
                )
                collector = build_metrics_collector_app(locator_configuration)
                collector_port = _available_loopback_port()
                config = Config()
                config.bind = [f"0.0.0.0:{collector_port}"]
                config.certfile = str(server_certificate_path)
                config.keyfile = str(server_key_path)
                config.ca_certs = str(ca_path)
                config.verify_mode = ssl.CERT_REQUIRED
                config.alpn_protocols = ["h2", "http/1.1"]
                collector_task = asyncio.create_task(
                    serve(collector, config, shutdown_trigger=collector_shutdown.wait)
                )
                await _wait_for_listener(collector_task, collector_port)

                docker_command = (
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    container_name,
                    "--label",
                    f"com.atlas-richie.sentinel-t005.owner={owner}",
                    "--publish",
                    "127.0.0.1::18094/tcp",
                    "--volume",
                    f"{repository_root}:/workspace",
                    "--volume",
                    f"{root}:/acceptance:ro",
                    "--volume",
                    "sentinel-rust-cargo-cache:/cache",
                    "--env",
                    "CARGO_HOME=/cache",
                    "--env",
                    "HTTP_ADDR=0.0.0.0:18094",
                    "--env",
                    "RULE_SOURCE_PROVIDER=consul",
                    "--env",
                    "RULE_SOURCE_PROFILE=managed-envelope-v1",
                    "--env",
                    f"CONSUL_URL=http://host.docker.internal:{parsed_consul.port}",
                    "--env",
                    f"CONSUL_KEY={key}",
                    "--env",
                    f"RULE_BINDING_ID={binding_id}",
                    "--env",
                    "RULE_PROFILE_ID=sentinel-rust-v1",
                    "--env",
                    f"METRICS_COLLECTOR_URL=https://host.docker.internal:{collector_port}",
                    "--env",
                    f"METRICS_REPORTER_ID={reporter_id}",
                    "--env",
                    "METRICS_CLIENT_CERT=/acceptance/reporter-cert.pem",
                    "--env",
                    "METRICS_CLIENT_KEY=/acceptance/reporter-key.pem",
                    "--env",
                    "METRICS_COLLECTOR_CA=/acceptance/ca.pem",
                    "--env",
                    "POLL_INTERVAL_MS=100",
                    "--workdir",
                    f"/workspace/{rust_project.relative_to(repository_root)}",
                    "rust:1.89-slim",
                    "sh",
                    "-c",
                    "cargo run --locked --bin sentinel-rust-runtime-demo",
                )
                started = await asyncio.to_thread(
                    subprocess.run,
                    docker_command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                container_id = started.stdout.strip()
                inspect = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "inspect", "--format", "{{.Config.Labels}}", container_id],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertIn(owner, inspect.stdout)
                mapped = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "port", container_id, "18094/tcp"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                host_port = int(mapped.stdout.strip().rsplit(":", 1)[1])
                runtime_url = f"http://127.0.0.1:{host_port}"
                async with httpx.AsyncClient(timeout=3) as runtime:
                    deadline = asyncio.get_running_loop().time() + 360
                    rules_response: httpx.Response | None = None
                    while asyncio.get_running_loop().time() < deadline:
                        container_state = await asyncio.to_thread(
                            subprocess.run,
                            [
                                "docker",
                                "inspect",
                                "--format",
                                "{{.State.Running}}",
                                container_id,
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        if (
                            container_state.returncode != 0
                            or container_state.stdout.strip() != "true"
                        ):
                            logs = await asyncio.to_thread(
                                subprocess.run,
                                ["docker", "logs", container_id],
                                capture_output=True,
                                text=True,
                                timeout=15,
                            )
                            self.fail(
                                "Rust runtime container exited before readiness:\n"
                                f"{logs.stdout}\n{logs.stderr}"
                            )
                        try:
                            health = await runtime.get(f"{runtime_url}/health")
                            if health.status_code == 200:
                                rules_response = await runtime.get(f"{runtime_url}/rules")
                                if rules_response.status_code == 200:
                                    break
                        except httpx.TransportError:
                            await asyncio.sleep(0.5)
                    self.assertIsNotNone(
                        rules_response,
                        "Rust runtime did not become ready after compiling and loading Consul rules",
                    )
                    assert rules_response is not None
                    rules = rules_response.json()
                    self.assertTrue(rules["rules_loaded"])
                    self.assertEqual(rules["rule_count"], 1)
                    self.assertEqual(rules["managed_publication"]["binding_id"], binding_id)
                    self.assertEqual(
                        rules["managed_publication"]["publication_id"], publication_id
                    )
                    self.assertEqual(
                        rules["managed_publication"]["target_version_id"], version_id
                    )
                    self.assertTrue(rules["source_revision"])

                    statuses: list[int] = []
                    for _ in range(6):
                        response = await runtime.get(f"{runtime_url}/demo")
                        statuses.append(response.status_code)
                        if 200 in statuses and 429 in statuses:
                            break
                        await asyncio.sleep(0.03)
                    self.assertIn(200, statuses)
                    self.assertIn(429, statuses)

                async def durable_facts_ready() -> tuple[bool, str | None]:
                    async with async_sessionmaker(engine)() as session:
                        observation_rows = (
                            await session.scalars(select(RuleLoadObservationInboxRecord))
                        ).all()
                        receipt_rows = (
                            await session.scalars(select(RulePublicationReceiptInboxRecord))
                        ).all()
                        metric_rows = (
                            await session.scalars(
                                select(MetricsSnapshotRecord).where(
                                    MetricsSnapshotRecord.certificate_principal == principal
                                )
                            )
                        ).all()
                        binding = await session.get(MetricsReporterBindingRecord, principal)
                    if not (observation_rows and receipt_rows and metric_rows and binding):
                        return False, None
                    latest_snapshot_row = max(metric_rows, key=lambda row: row.sequence)
                    latest_snapshot = decode_metrics_snapshot(latest_snapshot_row.body)
                    epoch = str(latest_snapshot.startup_epoch)
                    counters = {item.name: item.value for item in latest_snapshot.counters}
                    ready = (
                        binding.current_epoch == epoch
                        and observation_rows[0].process_epoch == epoch
                        and receipt_rows[0].process_epoch == epoch
                        and receipt_rows[0].binding_id == binding_id
                        and receipt_rows[0].publication_id == publication_id
                        and receipt_rows[0].target_version_id == version_id
                        and counters[CounterName.HTTP_REQUESTS_COMPLETED] >= len(statuses)
                        and counters[CounterName.SENTINEL_ENTRIES_ADMITTED] >= 1
                        and counters[CounterName.SENTINEL_ENTRIES_BLOCKED] >= 1
                    )
                    return ready, epoch

                deadline = asyncio.get_running_loop().time() + 45
                epoch: str | None = None
                while asyncio.get_running_loop().time() < deadline:
                    ready, epoch = await durable_facts_ready()
                    if ready:
                        break
                    await asyncio.sleep(0.25)
                self.assertIsNotNone(epoch, "Rust observations did not follow Metrics V2 epoch enrollment")
                ready, epoch = await durable_facts_ready()
                self.assertTrue(ready, "Collector did not durably accept matching Rust process facts")
                assert epoch is not None

                worker_time = datetime.now(UTC).replace(microsecond=0)
                observation_projection = await RunRuleLoadObservationProjectionWorker(
                    SqlAlchemyRuleLoadObservationProjectionQueue(engine)
                ).run_once(now=worker_time, batch_size=10)
                receipt_projection = await RunRulePublicationReceiptProjectionWorker(
                    SqlAlchemyRulePublicationReceiptProjectionQueue(engine)
                ).run_once(now=worker_time, batch_size=10)
                self.assertEqual(observation_projection.delivered, 1)
                self.assertEqual(receipt_projection.delivered, 1)

                class AcceptanceSessionReader:
                    async def read_active_session(self, _digest: str):
                        return ActiveAccountSession(
                            "acceptance-account", "acceptance-admin", "admin", "session-epoch"
                        )

                app = build_app(
                    bootstrap_initialization_reader=object(),
                    setup_window_reader=object(),
                    bootstrap_operator_verifier=object(),
                    current_session_reader=AcceptanceSessionReader(),
                    current_session_revoker=object(),
                    account_directory_reader=object(),
                    allowed_browser_origins=frozenset({"https://acceptance.example.test"}),
                    rule_load_observation_reader=ReadRuleLoadObservations(
                        SqlAlchemyRuleLoadObservationReader(engine)
                    ),
                    rule_publication_detail_reader=SqlAlchemyRulePublicationReader(engine),
                    rule_publication_receipt_reader=SqlAlchemyRulePublicationReceiptStore(engine),
                )
                api_cookie = "synthetic-rust-runtime-session-cookie-0001"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://console.test"
                ) as console:
                    console.cookies.set("sentinel_session", api_cookie)
                    observation_response = await console.get(
                        "/api/v2/rules/load-observations"
                        f"?environmentId=acceptance&appId=rust-consul-runtime&bindingId={binding_id}",
                        headers={"x-request-id": "rust-consul-observation-readback"},
                    )
                    receipt_response = await console.get(
                        f"/api/v1/rulesets/{binding_id}/publications/{publication_id}/receipts?page=1&pageSize=20",
                        headers={"x-request-id": "rust-consul-receipt-readback"},
                    )
                self.assertEqual(observation_response.status_code, 200)
                observation_item = observation_response.json()["items"][0]
                self.assertEqual(observation_item["processEpoch"], epoch)
                self.assertEqual(observation_item["loadState"], "applied")
                self.assertEqual(receipt_response.status_code, 200)
                receipt_body = receipt_response.json()
                self.assertEqual(receipt_body["total"], 1)
                self.assertEqual(receipt_body["applied"], 1)
                self.assertEqual(receipt_body["items"][0]["state"], "applied")
                self.assertEqual(receipt_body["items"][0]["processEpoch"], epoch)
            finally:
                if container_id is not None:
                    owner_check = await asyncio.to_thread(
                        subprocess.run,
                        [
                            "docker",
                            "inspect",
                            "--format",
                            '{{ index .Config.Labels "com.atlas-richie.sentinel-t005.owner" }}',
                            container_id,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if owner_check.returncode == 0 and owner_check.stdout.strip() == owner:
                        await asyncio.to_thread(
                            subprocess.run,
                            ["docker", "rm", "-f", container_id],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=30,
                        )
                        absent = await asyncio.to_thread(
                            subprocess.run,
                            ["docker", "inspect", container_id],
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        self.assertNotEqual(absent.returncode, 0)
                    elif owner_check.returncode == 0:
                        self.fail("refusing to remove a Rust runtime container with a foreign owner")
                if collector_task is not None:
                    collector_shutdown.set()
                    await asyncio.wait_for(collector_task, timeout=5)
                await engine.dispose()
                async with httpx.AsyncClient(timeout=5) as consul:
                    deleted = await consul.delete(consul_key_url)
                    self.assertEqual(deleted.status_code, 200)

    async def test_rust_metrics_reporter_receives_real_mtls_durable_ack_and_sql_commit(
        self,
    ) -> None:
        if shutil.which("docker") is None:
            self.skipTest("Rust cross-process acceptance requires Docker")
        with tempfile.TemporaryDirectory(
            prefix="sentinel-rust-metrics-mtls-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="host.docker.internal",
                is_ca=False,
                is_server=True,
                server_dns_name="host.docker.internal",
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="rust-metrics-reporter",
                is_ca=False,
                is_server=False,
            )
            ca_path = root / "ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(_certificate_pem(reporter_certificate))
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))

            database_url = _test_database_url(root)
            engine = create_async_engine(database_url)
            try:
                await upgrade_database(engine)
            finally:
                await engine.dispose()

            locator_path = root / "runtime-locator.json"
            cipher = AesGcmSecretCipher("rust-metrics-test", {"rust-metrics-test": b"r" * 32})
            await RuntimeDatabaseLocatorFileStore(locator_path, cipher).write(
                database_url, expected_revision=None
            )
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path,
                "rust-metrics-test",
                {"rust-metrics-test": b"r" * 32},
            )
            reporter_id = f"rust-metrics-{uuid4()}"
            principal = f"spiffe://sentinel.test/rust-metrics/{uuid4()}"
            reporter_admin, reporter_runtime = build_metrics_reporter_admin(
                locator_configuration
            )
            await reporter_runtime.start()
            await reporter_admin.enroll(
                MetricsReporterBinding(
                    certificate_principal=principal,
                    certificate_sha256=reporter_certificate.fingerprint(
                        hashes.SHA256()
                    ).hex(),
                    reporter_id=reporter_id,
                    environment_id="acceptance",
                    app_id="rust-metrics-demo",
                    instance_id=f"rust-worker-{uuid4()}",
                    process_id=f"rust-process-{uuid4()}",
                )
            )
            await reporter_runtime.dispose()

            app = build_metrics_collector_app(locator_configuration)
            port = _available_loopback_port()
            config = Config()
            config.bind = [f"0.0.0.0:{port}"]
            config.certfile = str(server_certificate_path)
            config.keyfile = str(server_key_path)
            config.ca_certs = str(ca_path)
            config.verify_mode = ssl.CERT_REQUIRED
            config.alpn_protocols = ["h2", "http/1.1"]
            shutdown = asyncio.Event()
            server_task = asyncio.create_task(
                serve(app, config, shutdown_trigger=shutdown.wait)
            )
            try:
                await _wait_for_listener(server_task, port)
                repository_root = Path(__file__).resolve().parents[4]
                rust_project = repository_root / "components/sentinel/demos/rust-sentinel"
                rust_command = (
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{repository_root}:/workspace",
                    "-v",
                    f"{root}:/acceptance:ro",
                    "-v",
                    "sentinel-rust-cargo-cache:/cache",
                    "-e",
                    "CARGO_HOME=/cache",
                    "-e",
                    "RUST_METRICS_TEST_EPOCH=8f3e16fc-54e8-4b37-a40c-5ae98da1fd44",
                    "-e",
                    f"METRICS_COLLECTOR_URL=https://host.docker.internal:{port}",
                    "-e",
                    f"METRICS_REPORTER_ID={reporter_id}",
                    "-e",
                    "METRICS_CLIENT_CERT=/acceptance/reporter-cert.pem",
                    "-e",
                    "METRICS_CLIENT_KEY=/acceptance/reporter-key.pem",
                    "-e",
                    "METRICS_COLLECTOR_CA=/acceptance/ca.pem",
                    "-w",
                    f"/workspace/{rust_project.relative_to(repository_root)}",
                    "rust:1.89-slim",
                    "sh",
                    "-c",
                    "cargo run --locked --example metrics_v2_collector_acceptance",
                )
                process = await asyncio.create_subprocess_exec(
                    *rust_command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=240
                )
                self.assertEqual(
                    process.returncode,
                    0,
                    f"Rust reporter did not confirm Collector durable ACK; "
                    f"stdout={stdout.decode(errors='replace')[-4000:]!r}; "
                    f"stderr={stderr.decode(errors='replace')[-4000:]!r}",
                )
                self.assertIn(
                    b"Rust Metrics V2 durable receipt confirmed", stdout
                )
            finally:
                shutdown.set()
                await asyncio.wait_for(server_task, timeout=5)

            read_engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(read_engine)() as session:
                    snapshots = (
                        await session.scalars(
                            select(MetricsSnapshotRecord).where(
                                MetricsSnapshotRecord.certificate_principal == principal
                            )
                        )
                    ).all()
                self.assertEqual(len(snapshots), 1)
                snapshot = decode_metrics_snapshot(snapshots[0].body)
                self.assertEqual(snapshot.reporter_id, reporter_id)
                self.assertEqual(str(snapshot.startup_epoch), "8f3e16fc-54e8-4b37-a40c-5ae98da1fd44")
                self.assertEqual(snapshot.sequence, 1)
                counters = {item.name: item.value for item in snapshot.counters}
                self.assertEqual(counters[CounterName.HTTP_REQUESTS_COMPLETED], 2)
                self.assertEqual(counters[CounterName.SENTINEL_ENTRIES_ADMITTED], 1)
                self.assertEqual(counters[CounterName.SENTINEL_ENTRIES_BLOCKED], 1)
                self.assertEqual(counters[CounterName.BUSINESS_TRANSACTIONS_COMPLETED], 1)
                self.assertEqual(snapshot.histograms[0].sample_count, 2)
                self.assertEqual(
                    hashlib.sha256(snapshots[0].body).hexdigest(),
                    snapshots[0].body_sha256,
                )
            finally:
                await read_engine.dispose()

    async def test_rust_rule_reporter_delivers_observation_and_managed_receipt_over_mtls(
        self,
    ) -> None:
        if shutil.which("docker") is None:
            self.skipTest("Rust cross-process acceptance requires Docker")
        with tempfile.TemporaryDirectory(
            prefix="sentinel-rust-rule-reporting-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="host.docker.internal",
                is_ca=False,
                is_server=True,
                server_dns_name="host.docker.internal",
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="rust-rule-reporter",
                is_ca=False,
                is_server=False,
            )
            ca_path = root / "ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(_certificate_pem(reporter_certificate))
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))

            database_url = _test_database_url(root)
            engine = create_async_engine(database_url)
            now = datetime.now(UTC).replace(microsecond=0)
            account_id = str(uuid4())
            source_id = f"rust-source-{uuid4()}"
            binding_id = f"rust-binding-{uuid4()}"
            version_id = f"rust-version-{uuid4()}"
            publication_id = f"rust-publication-{uuid4()}"
            principal = f"spiffe://sentinel.test/rust-reporting/{uuid4()}"
            process_epoch = str(uuid4())
            payload = (
                b'[{"resource":"sentinel-rust-managed-demo-resource",'
                b'"grade":1,"count":10,"strategy":0,"controlBehavior":0,'
                b'"limitApp":"default"}]'
            )
            payload_digest = hashlib.sha256(payload).hexdigest()
            try:
                await upgrade_database(engine)
                async with engine.begin() as connection:
                    await connection.execute(
                        insert(AccountRecord).values(
                            account_id=account_id,
                            username=f"rust-{uuid4().hex[:16]}",
                            username_key=uuid4().hex,
                            password_hash="$argon2id$acceptance-only",
                            role_id="admin",
                            status="active",
                            built_in=False,
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await connection.execute(
                        insert(RegisteredConfigurationSourceRecord).values(
                            source_id=source_id,
                            revision="source-revision-1",
                            name="Rust acceptance source",
                            endpoint="https://consul.acceptance.invalid",
                            provider="consul",
                            location="acceptance/rust-rules",
                            authentication_mode="none",
                            credential_configured=False,
                            created_at=now,
                            updated_at=now,
                            updated_by_account_id=account_id,
                        )
                    )
                    await connection.execute(
                        insert(RuleBindingRecord).values(
                            binding_id=binding_id,
                            environment_id="acceptance",
                            app_id="rust-reporting-demo",
                            kind="flow",
                            profile="sentinel-rust-v1",
                            source_id=source_id,
                            location="acceptance/rust-rules",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await connection.execute(
                        insert(RuleValidationReceiptRecord).values(
                            validation_id=f"rust-validation-{uuid4()}",
                            binding_id=binding_id,
                            profile="sentinel-rust-v1",
                            base_checksum="base-checksum",
                            candidate_checksum="target-checksum",
                            is_publishable=True,
                            issues=[],
                            actor_account_id=account_id,
                            request_id=f"rust-request-{uuid4()}",
                            created_at=now,
                        )
                    )
                    validation_id = await connection.scalar(
                        select(RuleValidationReceiptRecord.validation_id).where(
                            RuleValidationReceiptRecord.binding_id == binding_id
                        )
                    )
                    await connection.execute(
                        insert(RuleSetVersionRecord).values(
                            version_id=version_id,
                            binding_id=binding_id,
                            kind="flow",
                            profile="sentinel-rust-v1",
                            base_version_id=None,
                            checksum="target-checksum",
                            name="Rust reporter target",
                            note="",
                            validation_id=validation_id,
                            records=[],
                            created_at=now,
                            created_by_account_id=account_id,
                        )
                    )
                    await connection.execute(
                        insert(RulePublicationRecord).values(
                            publication_id=publication_id,
                            binding_id=binding_id,
                            target_version_id=version_id,
                            target_checksum="target-checksum",
                            target_payload_checksum=payload_digest,
                            publication_sequence=1,
                            base_version_id=None,
                            created_at=now,
                            validation_state="succeeded",
                            validation_observed_at=now,
                            validation_reason=None,
                            write_state="succeeded",
                            write_observed_at=now,
                            write_reason=None,
                            read_back_state="succeeded",
                            read_back_observed_at=now,
                            read_back_reason=None,
                        )
                    )
                    await connection.execute(
                        insert(MetricsReporterBindingRecord).values(
                            certificate_principal=principal,
                            certificate_sha256=reporter_certificate.fingerprint(
                                hashes.SHA256()
                            ).hex(),
                            reporter_id=f"rust-reporter-{uuid4()}",
                            environment_id="acceptance",
                            app_id="rust-reporting-demo",
                            instance_id=f"rust-instance-{uuid4()}",
                            process_id=f"rust-process-{uuid4()}",
                            revoked_at=None,
                            current_epoch=process_epoch,
                            last_sequence=0,
                            last_elapsed_ns=None,
                            last_received_at=None,
                        )
                    )
            finally:
                await engine.dispose()

            locator_path = root / "runtime-locator.json"
            cipher = AesGcmSecretCipher("rust-rule-test", {"rust-rule-test": b"s" * 32})
            await RuntimeDatabaseLocatorFileStore(locator_path, cipher).write(
                database_url, expected_revision=None
            )
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path, "rust-rule-test", {"rust-rule-test": b"s" * 32}
            )
            app = build_metrics_collector_app(locator_configuration)
            port = _available_loopback_port()
            config = Config()
            config.bind = [f"0.0.0.0:{port}"]
            config.certfile = str(server_certificate_path)
            config.keyfile = str(server_key_path)
            config.ca_certs = str(ca_path)
            config.verify_mode = ssl.CERT_REQUIRED
            config.alpn_protocols = ["h2", "http/1.1"]
            shutdown = asyncio.Event()
            server_task = asyncio.create_task(
                serve(app, config, shutdown_trigger=shutdown.wait)
            )
            try:
                await _wait_for_listener(server_task, port)
                repository_root = Path(__file__).resolve().parents[4]
                rust_project = repository_root / "components/sentinel/demos/rust-sentinel"
                command = (
                    "docker", "run", "--rm",
                    "-v", f"{repository_root}:/workspace",
                    "-v", f"{root}:/acceptance:ro",
                    "-v", "sentinel-rust-cargo-cache:/cache",
                    "-e", "CARGO_HOME=/cache",
                    "-e", f"RUST_REPORTING_TEST_EPOCH={process_epoch}",
                    "-e", f"RULE_BINDING_ID={binding_id}",
                    "-e", "RULE_PROFILE_ID=sentinel-rust-v1",
                    "-e", f"RULE_PUBLICATION_ID={publication_id}",
                    "-e", f"RULE_TARGET_VERSION_ID={version_id}",
                    "-e", f"METRICS_COLLECTOR_URL=https://host.docker.internal:{port}",
                    "-e", "METRICS_CLIENT_CERT=/acceptance/reporter-cert.pem",
                    "-e", "METRICS_CLIENT_KEY=/acceptance/reporter-key.pem",
                    "-e", "METRICS_COLLECTOR_CA=/acceptance/ca.pem",
                    "-w", f"/workspace/{rust_project.relative_to(repository_root)}",
                    "rust:1.89-slim", "cargo", "run", "--locked",
                    "--example", "rule_reporting_collector_acceptance",
                )
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=240)
                self.assertEqual(
                    process.returncode,
                    0,
                    f"Rust rule reporter did not receive durable ACKs; stdout={stdout.decode(errors='replace')[-3000:]!r}; stderr={stderr.decode(errors='replace')[-3000:]!r}",
                )
                self.assertIn(b"Rust rule observation and managed receipt durable ACKs confirmed", stdout)
            finally:
                shutdown.set()
                await asyncio.wait_for(server_task, timeout=5)

            verification_engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(verification_engine)() as session:
                    observations = (
                        await session.scalars(select(RuleLoadObservationInboxRecord))
                    ).all()
                    observation_outbox = (
                        await session.scalars(select(RuleLoadObservationOutboxRecord))
                    ).all()
                    receipts = (
                        await session.scalars(select(RulePublicationReceiptInboxRecord))
                    ).all()
                    receipt_outbox = (
                        await session.scalars(select(RulePublicationReceiptOutboxRecord))
                    ).all()
                self.assertEqual(len(observations), 1)
                self.assertEqual(len(observation_outbox), 1)
                self.assertEqual(len(receipts), 1)
                self.assertEqual(len(receipt_outbox), 1)
                observation_body = json.loads(observations[0].body)
                receipt_body = json.loads(receipts[0].body)
                self.assertEqual(observation_body["event_kind"], "snapshot_applied")
                self.assertEqual(observation_body["process_epoch"], process_epoch)
                self.assertEqual(observation_body["binding_id"], binding_id)
                self.assertEqual(receipt_body["process_epoch"], process_epoch)
                self.assertEqual(receipt_body["binding_id"], binding_id)
                self.assertEqual(receipt_body["publication_id"], publication_id)
                self.assertEqual(receipt_body["target_version_id"], version_id)
                self.assertEqual(receipt_body["target_payload_sha256"], payload_digest)
                self.assertEqual(observation_outbox[0].state, "pending")
                self.assertEqual(receipt_outbox[0].state, "pending")
            finally:
                await verification_engine.dispose()

    async def test_rule_load_observation_uses_real_mtls_socket_and_durable_ack(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sentinel-rule-load-mtls-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="127.0.0.1",
                is_ca=False,
                is_server=True,
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="rule-load-reporter",
                is_ca=False,
                is_server=False,
            )
            unregistered_certificate, unregistered_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="unregistered-rule-load-reporter",
                is_ca=False,
                is_server=False,
            )
            ca_path = root / "ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            unregistered_certificate_path = root / "unregistered-cert.pem"
            unregistered_key_path = root / "unregistered-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(
                _certificate_pem(reporter_certificate)
            )
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))
            unregistered_certificate_path.write_bytes(
                _certificate_pem(unregistered_certificate)
            )
            unregistered_key_path.write_bytes(_private_key_pem(unregistered_key))

            database_url = f"sqlite+aiosqlite:///{root / 'rule-load.sqlite3'}"
            engine = create_async_engine(database_url)
            try:
                await upgrade_database(engine)
                now = datetime.now(UTC).replace(microsecond=0)
                account_id = str(uuid4())
                username = f"rule-load-{uuid4().hex[:16]}"
                source_id = f"rule-load-source-{uuid4()}"
                binding_id = f"rule-load-binding-{uuid4()}"
                principal = f"spiffe://sentinel.test/rule-load/{uuid4()}"
                process_epoch = str(uuid4())
                certificate_sha256 = reporter_certificate.fingerprint(
                    hashes.SHA256()
                ).hex()
                async with engine.begin() as connection:
                    await connection.execute(
                        insert(AccountRecord).values(
                            account_id=account_id,
                            username=username,
                            username_key=username.casefold(),
                            password_hash="$argon2id$acceptance-only",
                            role_id="admin",
                            status="active",
                            built_in=False,
                            revision=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await connection.execute(
                        insert(RegisteredConfigurationSourceRecord).values(
                            source_id=source_id,
                            revision="source-revision-1",
                            name="Rule Load mTLS test source",
                            endpoint="https://nacos.acceptance.invalid",
                            provider="nacos",
                            location="synthetic/config",
                            authentication_mode="none",
                            credential_configured=False,
                            created_at=now,
                            updated_at=now,
                            updated_by_account_id=account_id,
                        )
                    )
                    await connection.execute(
                        insert(RuleBindingRecord).values(
                            binding_id=binding_id,
                            environment_id="acceptance",
                            app_id="rule-load-app",
                            kind="flow",
                            profile="sentinel-python-v1",
                            source_id=source_id,
                            location="flow-rules.json",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    await connection.execute(
                        insert(MetricsReporterBindingRecord).values(
                            certificate_principal=principal,
                            certificate_sha256=certificate_sha256,
                            reporter_id=f"rule-load-reporter-{uuid4()}",
                            environment_id="acceptance",
                            app_id="rule-load-app",
                            instance_id="worker-0",
                            process_id="process-1",
                            revoked_at=None,
                            current_epoch=process_epoch,
                            last_sequence=0,
                        )
                    )
            finally:
                await engine.dispose()

            locator_path = root / "runtime-locator.json"
            cipher = AesGcmSecretCipher("rule-load-test", {"rule-load-test": b"q" * 32})
            await RuntimeDatabaseLocatorFileStore(locator_path, cipher).write(
                database_url, expected_revision=None
            )
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path,
                "rule-load-test",
                {"rule-load-test": b"q" * 32},
            )
            app = build_metrics_collector_app(locator_configuration)
            port = _available_loopback_port()
            config = Config()
            config.bind = [f"127.0.0.1:{port}"]
            config.certfile = str(server_certificate_path)
            config.keyfile = str(server_key_path)
            config.ca_certs = str(ca_path)
            config.verify_mode = ssl.CERT_REQUIRED
            config.alpn_protocols = ["h2", "http/1.1"]
            shutdown = asyncio.Event()
            server_task = asyncio.create_task(
                serve(app, config, shutdown_trigger=shutdown.wait)
            )
            observation = RuleLoadObservationV1(
                observation_id=str(uuid4()),
                process_epoch=process_epoch,
                sequence=1,
                binding_id=binding_id,
                profile_id="sentinel-python-v1",
                event_kind=RuleLoadEventKind.SNAPSHOT_APPLIED,
                active_snapshot=RuleLoadSnapshotV1(
                    source_revision="provider-revision-1",
                    source_bytes_sha256=hashlib.sha256(b"provider bytes").hexdigest(),
                    canonical_rules_sha256=hashlib.sha256(
                        b"canonical rules"
                    ).hexdigest(),
                    membership_complete=True,
                    members=(
                        RuleLoadMemberFingerprint(
                            RuleKind.FLOW,
                            hashlib.sha256(b"one flow rule").hexdigest(),
                        ),
                    ),
                ),
                attempt=None,
                observed_at=now,
            )
            body = encode_rule_load_observation(observation)
            try:
                await _wait_for_listener(server_task, port)
                no_certificate_context = ssl.create_default_context(cafile=str(ca_path))
                async with httpx.AsyncClient(
                    verify=no_certificate_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as anonymous_client:
                    with self.assertRaises(httpx.TransportError):
                        await anonymous_client.post(
                            "/api/reporting/v1/rule-load-observations",
                            content=body,
                            headers={"content-type": "application/json"},
                        )

                unregistered_context = ssl.create_default_context(cafile=str(ca_path))
                unregistered_context.load_cert_chain(
                    certfile=str(unregistered_certificate_path),
                    keyfile=str(unregistered_key_path),
                )
                async with httpx.AsyncClient(
                    verify=unregistered_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as unregistered_client:
                    unregistered = await unregistered_client.post(
                        "/api/reporting/v1/rule-load-observations",
                        content=body,
                        headers={"content-type": "application/json"},
                    )
                self.assertEqual(unregistered.status_code, 401)

                reporter_context = ssl.create_default_context(cafile=str(ca_path))
                reporter_context.load_cert_chain(
                    certfile=str(reporter_certificate_path),
                    keyfile=str(reporter_key_path),
                )
                async with httpx.AsyncClient(
                    verify=reporter_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as reporter_client:
                    first = await reporter_client.post(
                        "/api/reporting/v1/rule-load-observations",
                        content=body,
                        headers={"content-type": "application/json"},
                    )
                    retry = await reporter_client.post(
                        "/api/reporting/v1/rule-load-observations",
                        content=body,
                        headers={"content-type": "application/json"},
                    )
                self.assertEqual(first.status_code, 204)
                self.assertEqual(retry.status_code, 204)
            finally:
                shutdown.set()
                await asyncio.wait_for(server_task, timeout=5)

            verification_engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(verification_engine)() as session:
                    inbox_rows = (
                        await session.scalars(select(RuleLoadObservationInboxRecord))
                    ).all()
                    outbox_rows = (
                        await session.scalars(select(RuleLoadObservationOutboxRecord))
                    ).all()
                    sequence = await session.get(
                        RuleLoadObservationSequenceRecord,
                        (principal, process_epoch, binding_id),
                    )
                self.assertEqual(len(inbox_rows), 1)
                self.assertEqual(len(outbox_rows), 1)
                self.assertEqual(inbox_rows[0].certificate_principal, principal)
                self.assertEqual(inbox_rows[0].body, body)
                self.assertEqual(
                    inbox_rows[0].body_sha256, hashlib.sha256(body).hexdigest()
                )
                self.assertEqual(outbox_rows[0].state, "pending")
                self.assertEqual(sequence.last_sequence, 1)

                projection_worker = RunRuleLoadObservationProjectionWorker(
                    SqlAlchemyRuleLoadObservationProjectionQueue(verification_engine)
                )
                projected = await projection_worker.run_once(
                    now=datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
                )
                self.assertEqual(
                    (projected.claimed, projected.delivered, projected.parked),
                    (1, 1, 0),
                )

                class _AuthenticatedAcceptanceSession:
                    async def read_active_session(self, _session_digest: str):
                        return ActiveAccountSession(
                            account_id=account_id,
                            username=username,
                            role_id="admin",
                            session_epoch="acceptance-session-epoch",
                        )

                console_app = build_app(
                    bootstrap_initialization_reader=object(),
                    setup_window_reader=object(),
                    bootstrap_operator_verifier=object(),
                    current_session_reader=_AuthenticatedAcceptanceSession(),
                    current_session_revoker=object(),
                    account_directory_reader=object(),
                    allowed_browser_origins=frozenset(
                        {"https://console.acceptance.invalid"}
                    ),
                    rule_load_observation_reader=ReadRuleLoadObservations(
                        SqlAlchemyRuleLoadObservationReader(
                            verification_engine,
                            clock=lambda: (
                                datetime.now(UTC).replace(microsecond=0)
                                + timedelta(seconds=2)
                            ),
                        )
                    ),
                )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=console_app),
                    base_url="http://console.acceptance.invalid",
                ) as console_client:
                    console_client.cookies.set(
                        "sentinel_session",
                        "synthetic-authenticated-session-token-for-rule-load-acceptance",
                    )
                    readback = await console_client.get(
                        "/api/v2/rules/load-observations",
                        params={
                            "environmentId": "acceptance",
                            "appId": "rule-load-app",
                            "bindingId": binding_id,
                            "instanceId": "worker-0",
                        },
                        headers={"x-request-id": "rule-load-same-authority-acceptance"},
                    )
                self.assertEqual(readback.status_code, 200, readback.text)
                self.assertEqual(
                    readback.headers["x-request-id"],
                    "rule-load-same-authority-acceptance",
                )
                readback_body = readback.json()
                self.assertEqual(readback_body["targets"]["expected"], 1)
                self.assertEqual(readback_body["targets"]["observed"], 1)
                self.assertEqual(readback_body["total"], 1)
                self.assertEqual(readback_body["items"][0]["bindingId"], binding_id)
                self.assertEqual(readback_body["items"][0]["loadState"], "applied")
                self.assertEqual(
                    readback_body["items"][0]["activeSnapshot"]["canonicalRulesSha256"],
                    observation.active_snapshot.canonical_rules_sha256,
                )
            finally:
                await verification_engine.dispose()

    async def test_rule_publication_receipt_uses_real_mtls_socket_and_durable_ack(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sentinel-receipt-mtls-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="127.0.0.1",
                is_ca=False,
                is_server=True,
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="receipt-reporter",
                is_ca=False,
                is_server=False,
            )
            ca_path = root / "ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(
                _certificate_pem(reporter_certificate)
            )
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))

            database_url = f"sqlite+aiosqlite:///{root / 'receipt.sqlite3'}"
            bootstrap_engine = create_async_engine(database_url)
            await upgrade_database(bootstrap_engine)
            now = datetime.now(UTC).replace(microsecond=0)
            account_id = str(uuid4())
            source_id = f"receipt-source-{uuid4()}"
            binding_id = f"receipt-binding-{uuid4()}"
            version_id = f"receipt-version-{uuid4()}"
            publication_id = f"receipt-publication-{uuid4()}"
            principal = f"spiffe://sentinel.test/reporter/{uuid4()}"
            certificate_sha256 = reporter_certificate.fingerprint(hashes.SHA256()).hex()
            environment_id = f"receipt-env-{uuid4()}"
            app_id = f"receipt-app-{uuid4()}"
            instance_id = f"receipt-instance-{uuid4()}"
            process_id = f"receipt-process-{uuid4()}"
            process_epoch = str(uuid4())
            payload_digest = hashlib.sha256(b"[]").hexdigest()
            async with bootstrap_engine.begin() as connection:
                await connection.execute(
                    insert(AccountRecord).values(
                        account_id=account_id,
                        username=f"receipt-{uuid4().hex[:16]}",
                        username_key=uuid4().hex,
                        password_hash="$argon2id$acceptance-only",
                        role_id="admin",
                        status="active",
                        built_in=False,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(RegisteredConfigurationSourceRecord).values(
                        source_id=source_id,
                        revision="source-revision-1",
                        name="Receipt mTLS source",
                        endpoint="https://nacos.acceptance.invalid",
                        provider="nacos",
                        location="receipt/source",
                        authentication_mode="none",
                        credential_configured=False,
                        created_at=now,
                        updated_at=now,
                        updated_by_account_id=account_id,
                    )
                )
                await connection.execute(
                    insert(RuleBindingRecord).values(
                        binding_id=binding_id,
                        environment_id=environment_id,
                        app_id=app_id,
                        kind="flow",
                        profile="atlas-richie-sentinel-managed-v1",
                        source_id=source_id,
                        location="receipt/flow",
                        created_at=now,
                        updated_at=now,
                    )
                )
                await connection.execute(
                    insert(RuleValidationReceiptRecord).values(
                        validation_id=f"receipt-validation-{uuid4()}",
                        binding_id=binding_id,
                        profile="atlas-richie-sentinel-managed-v1",
                        base_checksum="base-checksum",
                        candidate_checksum="target-checksum",
                        is_publishable=True,
                        issues=[],
                        actor_account_id=account_id,
                        request_id=f"receipt-request-{uuid4()}",
                        created_at=now,
                    )
                )
                validation_id = await connection.scalar(
                    select(RuleValidationReceiptRecord.validation_id).where(
                        RuleValidationReceiptRecord.binding_id == binding_id
                    )
                )
                await connection.execute(
                    insert(RuleSetVersionRecord).values(
                        version_id=version_id,
                        binding_id=binding_id,
                        kind="flow",
                        profile="atlas-richie-sentinel-managed-v1",
                        base_version_id=None,
                        checksum="target-checksum",
                        name="Receipt target",
                        note="",
                        validation_id=validation_id,
                        records=[],
                        created_at=now,
                        created_by_account_id=account_id,
                    )
                )
                await connection.execute(
                    insert(RulePublicationRecord).values(
                        publication_id=publication_id,
                        binding_id=binding_id,
                        target_version_id=version_id,
                        target_checksum="target-checksum",
                        target_payload_checksum=payload_digest,
                        publication_sequence=1,
                        base_version_id=None,
                        created_at=now,
                        validation_state="succeeded",
                        validation_observed_at=now,
                        validation_reason=None,
                        write_state="succeeded",
                        write_observed_at=now,
                        write_reason=None,
                        read_back_state="succeeded",
                        read_back_observed_at=now,
                        read_back_reason=None,
                    )
                )
                await connection.execute(
                    insert(MetricsReporterBindingRecord).values(
                        certificate_principal=principal,
                        certificate_sha256=certificate_sha256,
                        reporter_id=f"receipt-reporter-{uuid4()}",
                        environment_id=environment_id,
                        app_id=app_id,
                        instance_id=instance_id,
                        process_id=process_id,
                        revoked_at=None,
                        current_epoch=process_epoch,
                        last_sequence=0,
                        last_elapsed_ns=None,
                        last_received_at=None,
                    )
                )
            await bootstrap_engine.dispose()

            locator_path = root / "runtime-locator.json"
            cipher = AesGcmSecretCipher("receipt-test", {"receipt-test": b"r" * 32})
            await RuntimeDatabaseLocatorFileStore(locator_path, cipher).write(
                database_url, expected_revision=None
            )
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path,
                "receipt-test",
                {"receipt-test": b"r" * 32},
            )
            app = build_metrics_collector_app(locator_configuration)
            port = _available_loopback_port()
            config = Config()
            config.bind = [f"127.0.0.1:{port}"]
            config.certfile = str(server_certificate_path)
            config.keyfile = str(server_key_path)
            config.ca_certs = str(ca_path)
            config.verify_mode = ssl.CERT_REQUIRED
            config.alpn_protocols = ["h2", "http/1.1"]
            shutdown = asyncio.Event()
            server_task = asyncio.create_task(
                serve(app, config, shutdown_trigger=shutdown.wait)
            )
            try:
                await _wait_for_listener(server_task, port)
                no_certificate_context = ssl.create_default_context(cafile=str(ca_path))
                async with httpx.AsyncClient(
                    verify=no_certificate_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as anonymous_client:
                    with self.assertRaises(httpx.TransportError):
                        await anonymous_client.post(
                            "/api/reporting/v1/rule-publication-receipts",
                            content=b"{}",
                            headers={"content-type": "application/json"},
                        )

                reporter_context = ssl.create_default_context(cafile=str(ca_path))
                reporter_context.load_cert_chain(
                    certfile=str(reporter_certificate_path),
                    keyfile=str(reporter_key_path),
                )

                class FixedCredentialProvider:
                    async def current(self) -> RuleReceiptTlsCredential:
                        return RuleReceiptTlsCredential(
                            "acceptance-v1", reporter_context
                        )

                collector_transport = RulePublicationReceiptHttpTransport(
                    f"https://127.0.0.1:{port}", FixedCredentialProvider()
                )
                delivered_bodies: list[bytes] = []

                class CommitThenDropAckTransport:
                    def __init__(self) -> None:
                        self._first = True

                    async def send(self, payload: bytes) -> None:
                        delivered_bodies.append(payload)
                        await collector_transport.send(payload)
                        if self._first:
                            self._first = False
                            raise RuleReceiptDeliveryError(
                                RuleReceiptDeliveryCode.TRANSPORT_UNAVAILABLE,
                                retryable=True,
                            )

                    async def aclose(self) -> None:
                        await collector_transport.aclose()

                repository = RuleRepository()
                reporter = RulePublicationReceiptReporter(
                    RulePublicationReceiptProducer(UUID(process_epoch)),
                    CommitThenDropAckTransport(),
                    RulePublicationReceiptReporterConfig(
                        max_attempts=2,
                        retry_base_seconds=0.001,
                        retry_max_seconds=0.001,
                    ),
                )
                await reporter.start(repository)
                provenance = RuleTargetProvenance(
                    binding_id=binding_id,
                    publication_id=publication_id,
                    target_version_id=version_id,
                    publication_sequence=1,
                    rule_kind=RuleTargetKind.FLOW,
                    profile_id="atlas-richie-sentinel-managed-v1",
                    payload_sha256=payload_digest,
                )
                self.assertTrue(
                    repository.apply_snapshot(
                        RuleSnapshot(
                            version=RuleVersion(1, 1, "c" * 64),
                            rules={},
                            source_id=source_id,
                            provenance=(provenance,),
                        )
                    )
                )
                await reporter.drain()
                self.assertEqual(delivered_bodies[0], delivered_bodies[1])
                self.assertEqual(reporter.stats.delivered, 1)
                self.assertEqual(reporter.stats.retries, 1)

                revoke_engine = create_async_engine(database_url)
                try:
                    async with revoke_engine.begin() as connection:
                        await connection.execute(
                            update(MetricsReporterBindingRecord)
                            .where(
                                MetricsReporterBindingRecord.certificate_principal
                                == principal
                            )
                            .values(revoked_at=datetime.now(UTC))
                        )
                finally:
                    await revoke_engine.dispose()
                self.assertTrue(
                    repository.apply_snapshot(
                        RuleSnapshot(
                            version=RuleVersion(1, 2, "d" * 64),
                            rules={},
                            source_id=source_id,
                            provenance=(provenance,),
                        )
                    )
                )
                await reporter.drain()
                self.assertEqual(reporter.stats.delivery_failed, 1)
                await reporter.aclose()
            finally:
                shutdown.set()
                await asyncio.wait_for(server_task, timeout=5)

            verification_engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(verification_engine)() as session:
                    inbox_rows = (
                        await session.scalars(select(RulePublicationReceiptInboxRecord))
                    ).all()
                    outbox_rows = (
                        await session.scalars(
                            select(RulePublicationReceiptOutboxRecord)
                        )
                    ).all()
                self.assertEqual(len(inbox_rows), 1)
                self.assertEqual(len(outbox_rows), 1)
                self.assertEqual(outbox_rows[0].state, "pending")
                self.assertEqual(inbox_rows[0].certificate_principal, principal)
                self.assertEqual(inbox_rows[0].sequence, 1)
                self.assertEqual(inbox_rows[0].binding_id, binding_id)
                self.assertEqual(inbox_rows[0].publication_id, publication_id)
                self.assertEqual(inbox_rows[0].target_version_id, version_id)
                self.assertEqual(
                    inbox_rows[0].body_sha256,
                    hashlib.sha256(delivered_bodies[0]).hexdigest(),
                )
            finally:
                await verification_engine.dispose()

    async def test_two_real_mtls_reporters_commit_rollup_and_query(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sentinel-metrics-mtls-", dir="/private/tmp"
        ) as temporary:
            root = Path(temporary)
            ca_certificate, ca_key = _create_ca()
            server_certificate, server_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="127.0.0.1",
                is_ca=False,
                is_server=True,
            )
            reporter_certificate, reporter_key = _create_signed_certificate(
                ca_certificate,
                ca_key,
                common_name="metrics-reporter-one",
                is_ca=False,
                is_server=False,
            )
            second_reporter_certificate, second_reporter_key = (
                _create_signed_certificate(
                    ca_certificate,
                    ca_key,
                    common_name="metrics-reporter-two",
                    is_ca=False,
                    is_server=False,
                )
            )
            ca_path = root / "test-ca.pem"
            server_certificate_path = root / "collector-cert.pem"
            server_key_path = root / "collector-key.pem"
            reporter_certificate_path = root / "reporter-cert.pem"
            reporter_key_path = root / "reporter-key.pem"
            second_reporter_certificate_path = root / "reporter-two-cert.pem"
            second_reporter_key_path = root / "reporter-two-key.pem"
            ca_path.write_bytes(_certificate_pem(ca_certificate))
            server_certificate_path.write_bytes(_certificate_pem(server_certificate))
            server_key_path.write_bytes(_private_key_pem(server_key))
            reporter_certificate_path.write_bytes(
                _certificate_pem(reporter_certificate)
            )
            reporter_key_path.write_bytes(_private_key_pem(reporter_key))
            second_reporter_certificate_path.write_bytes(
                _certificate_pem(second_reporter_certificate)
            )
            second_reporter_key_path.write_bytes(_private_key_pem(second_reporter_key))

            database_url = _test_database_url(root)
            bootstrap_engine = create_async_engine(database_url)
            try:
                await upgrade_database(bootstrap_engine)
                reporter_id = f"reporter-{uuid4()}"
                second_reporter_id = f"reporter-{uuid4()}"
                certificate_fingerprint = reporter_certificate.fingerprint(
                    hashes.SHA256()
                ).hex()
                second_certificate_fingerprint = (
                    second_reporter_certificate.fingerprint(hashes.SHA256()).hex()
                )
            finally:
                await bootstrap_engine.dispose()

            locator_path = root / "runtime-locator.json"
            cipher = AesGcmSecretCipher("metrics-test", {"metrics-test": b"l" * 32})
            locator_store = RuntimeDatabaseLocatorFileStore(locator_path, cipher)
            await locator_store.write(database_url, expected_revision=None)
            locator_configuration = RuntimeDatabaseLocatorConfiguration(
                locator_path,
                "metrics-test",
                {"metrics-test": b"l" * 32},
            )
            administration, admin_runtime = build_metrics_reporter_admin(
                locator_configuration
            )
            principal = "spiffe://sentinel.test/reporter/mtls-test"
            await admin_runtime.start()
            await administration.enroll(
                MetricsReporterBinding(
                    certificate_principal=principal,
                    certificate_sha256=certificate_fingerprint,
                    reporter_id=reporter_id,
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-1",
                    process_id="orders-1-worker-0",
                )
            )
            second_principal = f"spiffe://sentinel.test/reporter/{second_reporter_id}"
            await administration.enroll(
                MetricsReporterBinding(
                    certificate_principal=second_principal,
                    certificate_sha256=second_certificate_fingerprint,
                    reporter_id=second_reporter_id,
                    environment_id="test",
                    app_id="orders",
                    instance_id="orders-2",
                    process_id="orders-2-worker-0",
                )
            )
            await admin_runtime.dispose()
            app = build_metrics_collector_app(locator_configuration)
            observed_peer: dict[str, object] = {}

            async def observe_tls_scope(scope, receive, send) -> None:
                if scope["type"] == "http":
                    extensions = scope.get("extensions", {})
                    tls_extension = extensions.get("tls", {})
                    chain = tls_extension.get("client_cert_chain", ())
                    observed_peer["scheme"] = scope.get("scheme")
                    fingerprints = observed_peer.setdefault("fingerprints", [])
                    fingerprints.extend(
                        x509.load_pem_x509_certificate(value.encode("ascii"))
                        .fingerprint(hashes.SHA256())
                        .hex()
                        for value in chain
                    )
                await app(scope, receive, send)

            port = _available_loopback_port()
            config = Config()
            config.bind = [f"127.0.0.1:{port}"]
            config.certfile = str(server_certificate_path)
            config.keyfile = str(server_key_path)
            config.ca_certs = str(ca_path)
            config.verify_mode = ssl.CERT_REQUIRED
            config.alpn_protocols = ["h2", "http/1.1"]
            shutdown = asyncio.Event()
            server_task = asyncio.create_task(
                serve(observe_tls_scope, config, shutdown_trigger=shutdown.wait)
            )
            try:
                await _wait_for_listener(server_task, port)
                client_context = ssl.create_default_context(cafile=str(ca_path))
                async with httpx.AsyncClient(
                    verify=client_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as client_without_certificate:
                    with self.assertRaises(httpx.TransportError):
                        await client_without_certificate.post(
                            "/api/reporting/v2/snapshots",
                            content=b"{}",
                            headers={"content-type": "application/json"},
                        )

                reporter_context = ssl.create_default_context(cafile=str(ca_path))
                reporter_context.load_cert_chain(
                    certfile=str(reporter_certificate_path),
                    keyfile=str(reporter_key_path),
                )
                second_reporter_context = ssl.create_default_context(
                    cafile=str(ca_path)
                )
                second_reporter_context.load_cert_chain(
                    certfile=str(second_reporter_certificate_path),
                    keyfile=str(second_reporter_key_path),
                )
                incident_reporter = IncidentEventReporter(
                    IncidentEventHttpTransport(
                        f"https://127.0.0.1:{port}/api/reporting/v1/incidents",
                        _StaticIncidentCredentialProvider(
                            IncidentTlsCredential(
                                "incident-certificate-1", reporter_context
                            )
                        ),
                    ),
                    IncidentReporterConfig(max_attempts=2, retry_base_seconds=0.01),
                )
                first_epoch = uuid4()
                second_epoch = uuid4()
                first_baseline = encode_metrics_snapshot(
                    _metrics_snapshot(
                        reporter_id=reporter_id,
                        epoch=first_epoch,
                        sequence=1,
                        elapsed_ns=1_000_000_000,
                        http_count=100,
                    )
                )
                first_current = encode_metrics_snapshot(
                    _metrics_snapshot(
                        reporter_id=reporter_id,
                        epoch=first_epoch,
                        sequence=2,
                        elapsed_ns=2_000_000_000,
                        http_count=140,
                        histogram_finite=1,
                    )
                )
                incident_event = IncidentEventProducer(first_epoch).resource_pressure(
                    metric=ResourcePressureMetric.CPU_RATIO,
                    value=0.95,
                    threshold=0.9,
                    severity=IncidentSeverity.CRITICAL,
                )
                incident_body = encode_incident_event(incident_event)
                second_baseline = encode_metrics_snapshot(
                    _metrics_snapshot(
                        reporter_id=second_reporter_id,
                        epoch=second_epoch,
                        sequence=1,
                        elapsed_ns=1_000_000_000,
                        http_count=200,
                    )
                )
                second_current = encode_metrics_snapshot(
                    _metrics_snapshot(
                        reporter_id=second_reporter_id,
                        epoch=second_epoch,
                        sequence=2,
                        elapsed_ns=2_000_000_000,
                        http_count=260,
                        histogram_overflow=1,
                    )
                )
                receipt_instants: list[datetime] = []
                async with httpx.AsyncClient(
                    verify=reporter_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as reporter_client:
                    negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/agent",
                        json={"protocol_version": "atlas-richie.reporting/v1"},
                    )
                    self.assertEqual(negotiation.status_code, 200)
                    self.assertEqual(
                        negotiation.json()["compatibility"],
                        NegotiatedCompatibility.COMPATIBLE.value,
                    )
                    incompatible_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/agent",
                        json={"protocol_version": "atlas-richie.reporting/v2"},
                    )
                    self.assertEqual(incompatible_negotiation.status_code, 200)
                    self.assertEqual(
                        incompatible_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.INCOMPATIBLE.value,
                    )
                    restored_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/agent",
                        json={"protocol_version": "atlas-richie.reporting/v1"},
                    )
                    self.assertEqual(restored_negotiation.status_code, 200)
                    self.assertEqual(
                        restored_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.COMPATIBLE.value,
                    )
                    incident_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/incident-events",
                        json={"protocol_version": "atlas-richie.incident-events/v1"},
                    )
                    self.assertEqual(incident_negotiation.status_code, 200)
                    self.assertEqual(
                        incident_negotiation.json()["boundary"], "incident-events"
                    )
                    self.assertEqual(
                        incident_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.COMPATIBLE.value,
                    )
                    unsupported_incident_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/incident-events",
                        json={"protocol_version": "atlas-richie.incident-events/v2"},
                    )
                    self.assertEqual(unsupported_incident_negotiation.status_code, 200)
                    self.assertEqual(
                        unsupported_incident_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.INCOMPATIBLE.value,
                    )
                    restored_incident_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/incident-events",
                        json={"protocol_version": "atlas-richie.incident-events/v1"},
                    )
                    self.assertEqual(restored_incident_negotiation.status_code, 200)
                    self.assertEqual(
                        restored_incident_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.COMPATIBLE.value,
                    )
                    rule_load_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/rule-load-observation",
                        json={
                            "protocol_version": "atlas-richie.sentinel.rule-load-observation/v1"
                        },
                    )
                    self.assertEqual(rule_load_negotiation.status_code, 200)
                    self.assertEqual(
                        rule_load_negotiation.json()["boundary"],
                        "rule-load-observation",
                    )
                    self.assertEqual(
                        rule_load_negotiation.json()["compatibility"],
                        NegotiatedCompatibility.COMPATIBLE.value,
                    )
                    first_baseline_response = await reporter_client.post(
                        "/api/reporting/v2/snapshots",
                        content=first_baseline,
                        headers={"content-type": "application/json"},
                    )
                    first = await reporter_client.post(
                        "/api/reporting/v2/snapshots",
                        content=first_current,
                        headers={"content-type": "application/json"},
                    )
                    replay = await reporter_client.post(
                        "/api/reporting/v2/snapshots",
                        content=first_current,
                        headers={"content-type": "application/json"},
                    )
                    incident_response = await incident_reporter.report(incident_event)
                    incident_replay = await incident_reporter.report(incident_event)
                    receipt_instants.append(
                        _receipt_instant(first.json()["received_at"])
                    )
                    revoke_admin, revoke_runtime = build_metrics_reporter_admin(
                        locator_configuration
                    )
                    await revoke_runtime.start()
                    self.assertTrue(await revoke_admin.revoke(principal))
                    await revoke_runtime.dispose()
                    revoked = await reporter_client.post(
                        "/api/reporting/v2/snapshots",
                        content=first_current,
                        headers={"content-type": "application/json"},
                    )
                    revoked_incident = await reporter_client.post(
                        "/api/reporting/v1/incidents",
                        content=incident_body,
                        headers={"content-type": "application/json"},
                    )
                    revoked_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/agent",
                        json={"protocol_version": "atlas-richie.reporting/v1"},
                    )
                    revoked_incident_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/incident-events",
                        json={"protocol_version": "atlas-richie.incident-events/v1"},
                    )
                    revoked_rule_load_negotiation = await reporter_client.post(
                        "/api/reporting/v1/protocol-negotiations/rule-load-observation",
                        json={
                            "protocol_version": "atlas-richie.sentinel.rule-load-observation/v1"
                        },
                    )
                    await incident_reporter.aclose()
                async with httpx.AsyncClient(
                    verify=second_reporter_context,
                    base_url=f"https://127.0.0.1:{port}",
                    timeout=3,
                ) as second_client:
                    second_incident_negotiation = await second_client.post(
                        "/api/reporting/v1/protocol-negotiations/incident-events",
                        json={"protocol_version": "atlas-richie.incident-events/v1"},
                    )
                    second_baseline_response = await second_client.post(
                        "/api/reporting/v2/snapshots",
                        content=second_baseline,
                        headers={"content-type": "application/json"},
                    )
                    second_response = await second_client.post(
                        "/api/reporting/v2/snapshots",
                        content=second_current,
                        headers={"content-type": "application/json"},
                    )
                    receipt_instants.append(
                        _receipt_instant(second_response.json()["received_at"])
                    )
                self.assertEqual(first_baseline_response.status_code, 200)
                self.assertEqual(second_baseline_response.status_code, 200)
                self.assertEqual(second_incident_negotiation.status_code, 200)
                self.assertEqual(
                    second_incident_negotiation.json()["compatibility"],
                    NegotiatedCompatibility.COMPATIBLE.value,
                )
                self.assertEqual(
                    first.status_code,
                    200,
                    f"{first.text}; observed TLS scope={observed_peer!r}",
                )
                self.assertEqual(replay.status_code, 200, replay.text)
                self.assertEqual(incident_response.event_id, incident_event.event_id)
                self.assertEqual(incident_replay, incident_response)
                self.assertEqual(second_response.status_code, 200, second_response.text)
                self.assertEqual(revoked.status_code, 401, revoked.text)
                self.assertEqual(
                    revoked.json()["error"]["code"], "identity_not_enrolled"
                )
                self.assertEqual(revoked_incident.status_code, 401)
                self.assertEqual(revoked_negotiation.status_code, 401)
                self.assertEqual(revoked_incident_negotiation.status_code, 401)
                self.assertEqual(revoked_rule_load_negotiation.status_code, 401)
                self.assertEqual(
                    revoked_incident.json()["error"]["code"],
                    "identity_not_enrolled",
                )
                self.assertEqual(first.content, replay.content)
                self.assertEqual(observed_peer.get("scheme"), "https")
                observed_fingerprints = observed_peer.get("fingerprints")
                self.assertIsInstance(observed_fingerprints, list)
                self.assertGreaterEqual(len(observed_fingerprints), 1)
                self.assertIn(certificate_fingerprint, observed_fingerprints)
                self.assertIn(second_certificate_fingerprint, observed_fingerprints)
                self.assertEqual(
                    hashlib.sha256(first_current).hexdigest(),
                    json.loads(first.content)["body_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(incident_body).hexdigest(),
                    incident_response.body_sha256,
                )
            finally:
                shutdown.set()
                await asyncio.wait_for(server_task, timeout=5)

            read_engine = create_async_engine(database_url)
            try:
                async with async_sessionmaker(read_engine)() as session:
                    snapshots = (
                        await session.scalars(select(MetricsSnapshotRecord))
                    ).all()
                self.assertEqual(len(snapshots), 4)
                self.assertIn(first_current, {snapshot.body for snapshot in snapshots})
                self.assertIn(second_current, {snapshot.body for snapshot in snapshots})
                async with async_sessionmaker(read_engine)() as session:
                    incidents = (
                        await session.scalars(select(IncidentEventRecord))
                    ).all()
                self.assertEqual(len(incidents), 1)
                self.assertEqual(incidents[0].body, incident_body)
                self.assertEqual(incidents[0].process_epoch, str(first_epoch))
                async with async_sessionmaker(read_engine)() as session:
                    negotiations = (
                        await session.scalars(select(AgentReportingNegotiationRecord))
                    ).all()
                self.assertEqual(len(negotiations), 1)
                self.assertEqual(
                    negotiations[0].runtime_version, "atlas-richie.reporting/v1"
                )
                self.assertEqual(negotiations[0].compatibility, "compatible")
                async with async_sessionmaker(read_engine)() as session:
                    incident_negotiations = (
                        await session.execute(
                            select(
                                MetricsReporterBindingRecord.instance_id,
                                IncidentEventNegotiationRecord,
                            ).join(
                                IncidentEventNegotiationRecord,
                                IncidentEventNegotiationRecord.certificate_principal
                                == MetricsReporterBindingRecord.certificate_principal,
                            )
                        )
                    ).all()
                self.assertEqual(len(incident_negotiations), 2)
                self.assertEqual(
                    {row.instance_id for row in incident_negotiations},
                    {"orders-1", "orders-2"},
                )
                self.assertTrue(
                    all(
                        row.IncidentEventNegotiationRecord.runtime_version
                        == "atlas-richie.incident-events/v1"
                        for row in incident_negotiations
                    )
                )
                async with async_sessionmaker(read_engine)() as session:
                    rule_load_negotiations = (
                        await session.scalars(
                            select(RuleLoadObservationNegotiationRecord)
                        )
                    ).all()
                self.assertEqual(len(rule_load_negotiations), 1)
                self.assertEqual(
                    rule_load_negotiations[0].runtime_version,
                    "atlas-richie.sentinel.rule-load-observation/v1",
                )
                self.assertEqual(rule_load_negotiations[0].compatibility, "compatible")
                self.assertTrue(
                    all(
                        row.IncidentEventNegotiationRecord.compatibility == "compatible"
                        for row in incident_negotiations
                    )
                )

                async def resolve_engine():
                    return read_engine

                window_start = min(receipt_instants).replace(second=0, microsecond=0)
                window_end = max(receipt_instants).replace(
                    second=0, microsecond=0
                ) + timedelta(minutes=1)
                query = MetricQuery(
                    context=ObservationContext(
                        environment_id="test",
                        app_id="orders",
                        instance_id=None,
                        resource=None,
                        scope=ObservationScope.APPLICATION,
                        window=ObservationWindow(window_start, window_end),
                    ),
                    metrics=("http_qps", "rt_p95"),
                    step_ms=60_000,
                )
                bundle = await SQLAlchemyMetricsHistoryReader(
                    resolve_engine
                ).read_metrics(query)
                self.assertEqual(bundle.summary[0].value, 50)
                self.assertEqual(bundle.summary[0].coverage.reporting, 2)
                self.assertIsNone(bundle.summary[1].value)
                self.assertEqual(bundle.summary[1].quality.value, "partial")
            finally:
                await read_engine.dispose()


def _test_database_url(root: Path) -> str:
    configured = [
        (name, os.environ[name])
        for name in (
            "SENTINEL_CONSOLE_TEST_POSTGRES_URL",
            "SENTINEL_CONSOLE_TEST_MYSQL_URL",
        )
        if os.environ.get(name)
    ]
    if not configured:
        return f"sqlite+aiosqlite:///{root / 'metrics.sqlite3'}"
    if len(configured) != 1:
        raise AssertionError("acceptance requires exactly one disposable SQL dialect")

    variable, database_url = configured[0]
    parsed = urlsplit(database_url)
    provider = "POSTGRES" if variable.endswith("POSTGRES_URL") else "MYSQL"
    expected_scheme = (
        "postgresql+psycopg" if provider == "POSTGRES" else "mysql+asyncmy"
    )
    database_name = unquote(parsed.path.removeprefix("/"))
    if (
        parsed.scheme != expected_scheme
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or os.environ.get(f"SENTINEL_E2E_{provider}_HOST") != parsed.hostname
        or os.environ.get(f"SENTINEL_E2E_{provider}_PORT") != str(parsed.port)
        or os.environ.get(f"SENTINEL_E2E_{provider}_DATABASE") != database_name
        or not database_name.startswith("sentinel_console_test_")
        or parsed.username != "sentinel_e2e"
        or os.environ.get(f"SENTINEL_E2E_{provider}_USER") != parsed.username
    ):
        raise AssertionError("refusing a database outside the disposable SQL wrapper")
    return database_url


class _StaticIncidentCredentialProvider:
    """Return an ephemeral mTLS context for the loopback reporter acceptance."""

    def __init__(self, credential: IncidentTlsCredential) -> None:
        self._credential = credential

    async def current(self) -> IncidentTlsCredential:
        return self._credential


def _metrics_snapshot(
    *,
    reporter_id: str,
    epoch,
    sequence: int,
    elapsed_ns: int,
    http_count: int,
    histogram_finite: int = 0,
    histogram_overflow: int = 0,
) -> MetricsSnapshot:
    bucket_counts = [0] * (len(HTTP_REQUEST_DURATION_BOUNDARIES_NS) + 1)
    bucket_counts[0] = histogram_finite
    bucket_counts[-1] = histogram_overflow
    sample_count = histogram_finite + histogram_overflow
    sample_duration_ns = (
        histogram_finite * HTTP_REQUEST_DURATION_BOUNDARIES_NS[0]
        + histogram_overflow * 20_000_000_000
    )
    minimum_ns = HTTP_REQUEST_DURATION_BOUNDARIES_NS[0] if sample_count else None
    maximum_ns = (
        20_000_000_000
        if histogram_overflow
        else HTTP_REQUEST_DURATION_BOUNDARIES_NS[0]
        if sample_count
        else None
    )
    return MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=epoch,
        sequence=sequence,
        captured_at=datetime(2026, 10, 14, 1, 2, tzinfo=UTC),
        capture_elapsed_ns=elapsed_ns,
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, http_count),),
        histograms=(
            HistogramReading(
                HistogramName.HTTP_REQUEST_DURATION,
                HTTP_REQUEST_DURATION_BOUNDARIES_NS,
                tuple(bucket_counts),
                sample_count,
                sample_duration_ns,
                minimum_ns,
                maximum_ns,
            ),
        ),
    )


def _receipt_instant(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _create_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sentinel Test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + 1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return certificate, key


def _create_signed_certificate(
    ca_certificate: x509.Certificate,
    ca_key: rsa.RSAPrivateKey,
    *,
    common_name: str,
    is_ca: bool,
    is_server: bool,
    server_dns_name: str | None = None,
) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + 1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
    )
    if is_server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    *(
                        [x509.DNSName(server_dns_name)]
                        if server_dns_name is not None
                        else []
                    ),
                ]
            ),
            critical=False,
        )
        usage = x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH])
    else:
        usage = x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH])
    certificate = builder.add_extension(usage, critical=False).sign(
        ca_key, hashes.SHA256()
    )
    return certificate, key


def _certificate_pem(certificate: x509.Certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def _private_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


async def _wait_for_listener(server_task: asyncio.Task[None], port: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if server_task.done():
            await server_task
            raise AssertionError("Hypercorn stopped before opening the test listener")
        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.02)
        else:
            writer.close()
            await writer.wait_closed()
            return
    raise AssertionError("Hypercorn did not open the loopback test listener")
