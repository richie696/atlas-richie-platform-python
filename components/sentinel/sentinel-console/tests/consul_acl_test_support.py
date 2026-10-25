"""Disposable ACL-enabled Consul and private-CA HTTPS test endpoint."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import ssl
import subprocess
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from aiohttp import ClientSession, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    PinnedAioHttpJsonClient,
    RegisteredSourceTargetPolicy,
    RegisteredSourceTargetRule,
)

_CONSUL_IMAGE = "hashicorp/consul:1.21.1"


class DisposableConsulAclServer:
    """Own one loopback-only Consul container and an HTTPS test proxy.

    The real provider client trusts the test-only CA and sends an application
    token scoped to one exact KV key. The management token is exposed only to
    fixture provisioning calls in this test process.
    """

    def __init__(self, key: str) -> None:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("test Consul key must be a relative KV path")
        self.key = key
        self.container_name = f"sentinel-consul-acl-{uuid4().hex[:12]}"
        self.container_started = False
        self.port = 0
        self.native_https_port = 0
        self.proxy_port = 0
        self.endpoint = ""
        self.native_endpoint = ""
        self.management_token = ""
        self.application_token = ""
        self._source_probe_token: str | None = None
        self.client_ca_pem = ""
        self.client_ssl_context: ssl.SSLContext | None = None
        self.observed_requests: list[tuple[str, str | None]] = []
        self._proxy_runner: web.AppRunner | None = None
        self._certificate_directory: tempfile.TemporaryDirectory[str] | None = None
        self._response_drop_key: str | None = None
        self._response_committed: asyncio.Event | None = None
        self._response_drop_release: asyncio.Event | None = None
        self._response_dropped: asyncio.Event | None = None
        self._held_cas_key: str | None = None
        self._held_cas_received: asyncio.Event | None = None
        self._held_cas_release: asyncio.Event | None = None
        self._pre_upstream_drop_key: str | None = None
        self._pre_upstream_drop_received: asyncio.Event | None = None
        self._conflict_drop_key: str | None = None
        self._conflict_response_held: asyncio.Event | None = None
        self._conflict_response_release: asyncio.Event | None = None
        self._conflict_response_dropped: asyncio.Event | None = None

    async def start(self) -> None:
        """Start a disposable ACL agent with native HTTPS and a test proxy."""
        try:
            self._prepare_certificates()
            await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.container_name,
                    "--volume",
                    f"{self._certificate_directory.name}:/tmp/sentinel-test-tls:ro",
                    "--publish",
                    "127.0.0.1::8500/tcp",
                    "--publish",
                    "127.0.0.1::8501/tcp",
                    _CONSUL_IMAGE,
                    "agent",
                    "-dev",
                    "-client=0.0.0.0",
                    "-hcl",
                    """acl {
  enabled = true
  default_policy = "deny"
}
ports {
  https = 8501
}
tls {
  https {
    cert_file = "/tmp/sentinel-test-tls/certificate.pem"
    key_file = "/tmp/sentinel-test-tls/private-key.pem"
    verify_incoming = false
    verify_outgoing = false
  }
}""",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.container_started = True
            state_result = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}}",
                    self.container_name,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if state_result.stdout.strip() != "true":
                logs_result = await asyncio.to_thread(
                    subprocess.run,
                    ["docker", "logs", self.container_name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                raise RuntimeError(
                    "disposable Consul exited during startup: "
                    f"{logs_result.stdout}{logs_result.stderr}"
                )
            published_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "port", self.container_name, "8500/tcp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            published = published_result.stdout.strip()
            self.port = int(published.rsplit(":", 1)[1])
            published_https_result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "port", self.container_name, "8501/tcp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            published_https = published_https_result.stdout.strip()
            self.native_https_port = int(published_https.rsplit(":", 1)[1])
            self.native_endpoint = f"https://127.0.0.1:{self.native_https_port}"
            self.management_token = await asyncio.to_thread(self._bootstrap_acl_token)
            self.application_token = await asyncio.to_thread(
                self._create_single_key_acl_token
            )
            await self._start_tls_proxy()
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        """Stop the proxy, remove its ephemeral certificate, and delete Consul."""
        if self._proxy_runner is not None:
            await self._proxy_runner.cleanup()
            self._proxy_runner = None
        if self.container_started:
            await asyncio.to_thread(
                subprocess.run,
                ["docker", "rm", "--force", self.container_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.container_started = False
        if self._certificate_directory is not None:
            self._certificate_directory.cleanup()
            self._certificate_directory = None

    def registered_target_policy(self) -> RegisteredSourceTargetPolicy:
        """Return the network policy for this isolated test listener."""
        if self.proxy_port <= 0:
            raise RuntimeError("disposable Consul HTTPS proxy is not started")
        rule = RegisteredSourceTargetRule.create(
            ConfigurationSourceProvider.CONSUL,
            "127.0.0.1",
            ("127.0.0.1/32",),
            frozenset({self.proxy_port}),
        )
        return RegisteredSourceTargetPolicy((rule,))

    def registered_native_target_policy(self) -> RegisteredSourceTargetPolicy:
        """Return an exact-host policy for the Consul-owned HTTPS listener."""
        if self.native_https_port <= 0:
            raise RuntimeError("native Consul HTTPS listener is not started")
        rule = RegisteredSourceTargetRule.create(
            ConfigurationSourceProvider.CONSUL,
            "127.0.0.1",
            ("127.0.0.1/32",),
            frozenset({self.native_https_port}),
        )
        return RegisteredSourceTargetPolicy((rule,))

    def create_source_probe_token(self) -> str:
        """Create a read-only token for the Consul source-check contract."""
        if not self.management_token:
            raise RuntimeError("disposable Consul ACL server is not started")
        if self._source_probe_token is None:
            self._source_probe_token = self._create_read_only_source_token()
        return self._source_probe_token

    def http_client(self) -> PinnedAioHttpJsonClient:
        """Return the production HTTP adapter configured to trust the test CA."""
        if self.client_ssl_context is None:
            raise RuntimeError("disposable Consul HTTPS proxy is not started")
        return PinnedAioHttpJsonClient(ssl_context=self.client_ssl_context)

    def arm_response_drop_after_commit(self, key: str) -> None:
        """Hold one committed KV response until the caller process is stopped."""
        if self._proxy_runner is None or key != self.key:
            raise ValueError("response-loss barrier requires the server's exact KV key")
        if self._response_drop_key is not None:
            raise RuntimeError("a Consul response-loss barrier is already armed")
        self._response_drop_key = key
        self._response_committed = asyncio.Event()
        self._response_drop_release = asyncio.Event()
        self._response_dropped = asyncio.Event()

    async def wait_for_committed_response(self, *, timeout: float) -> None:
        """Wait until real Consul committed a write whose response is held."""
        event = self._response_committed
        if event is None:
            raise RuntimeError("Consul response-loss barrier is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)

    def release_dropped_response(self) -> None:
        """Close the blocked caller socket instead of forwarding its response."""
        event = self._response_drop_release
        if event is None:
            raise RuntimeError("Consul response-loss barrier is not armed")
        event.set()

    def arm_hold_cas_before_upstream(self, key: str) -> None:
        """Pause one CAS PUT before Consul so another process can race it."""
        if self._proxy_runner is None or key != self.key:
            raise ValueError("CAS barrier requires the server's exact KV key")
        if self._held_cas_key is not None:
            raise RuntimeError("a Consul CAS barrier is already armed")
        self._held_cas_key = key
        self._held_cas_received = asyncio.Event()
        self._held_cas_release = asyncio.Event()

    async def wait_for_held_cas(self, *, timeout: float) -> None:
        """Wait until the production CAS request is held ahead of Consul."""
        event = self._held_cas_received
        if event is None:
            raise RuntimeError("Consul CAS barrier is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)

    def release_held_cas(self) -> None:
        """Release the held CAS; repeated cleanup calls are harmless."""
        event = self._held_cas_release
        if event is not None:
            event.set()

    def arm_cas_drop_before_upstream(self, key: str) -> None:
        """Reset one CAS request after proxy receipt but before Consul dispatch."""
        if self._proxy_runner is None or key != self.key:
            raise ValueError("pre-upstream CAS drop requires the server's exact KV key")
        if self._pre_upstream_drop_key is not None:
            raise RuntimeError("a pre-upstream CAS drop is already armed")
        self._pre_upstream_drop_key = key
        self._pre_upstream_drop_received = asyncio.Event()

    async def wait_for_pre_upstream_cas_drop(self, *, timeout: float) -> None:
        """Wait until a matching CAS was reset before forwarding to Consul."""
        event = self._pre_upstream_drop_received
        if event is None:
            raise RuntimeError("pre-upstream CAS drop is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)
        if self._pre_upstream_drop_received is event:
            self._pre_upstream_drop_received = None

    async def wait_for_dropped_response(self, *, timeout: float) -> None:
        """Wait until the proxy reset the response path after the upstream commit."""
        event = self._response_dropped
        if event is None:
            raise RuntimeError("Consul response-loss barrier is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)
        self._response_drop_key = None
        self._response_committed = None
        self._response_drop_release = None
        self._response_dropped = None

    def arm_drop_cas_conflict_response(self, key: str) -> None:
        """Drop one provider-rejected CAS response after Consul returns false."""
        if self._proxy_runner is None or key != self.key:
            raise ValueError("CAS conflict response drop requires the exact KV key")
        if self._conflict_drop_key is not None:
            raise RuntimeError("a Consul CAS conflict response drop is already armed")
        self._conflict_drop_key = key
        self._conflict_response_held = asyncio.Event()
        self._conflict_response_release = asyncio.Event()
        self._conflict_response_dropped = asyncio.Event()

    async def wait_for_held_cas_conflict_response(self, *, timeout: float) -> None:
        """Wait until Consul rejected the stale CAS and its response is held."""
        event = self._conflict_response_held
        if event is None:
            raise RuntimeError("Consul CAS conflict response drop is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)

    def release_dropped_cas_conflict_response(self) -> None:
        """Allow the proxy to close the caller socket after a rejected CAS."""
        event = self._conflict_response_release
        if event is not None:
            event.set()

    async def wait_for_dropped_cas_conflict_response(self, *, timeout: float) -> None:
        """Wait until the rejected CAS response was hidden from the client."""
        event = self._conflict_response_dropped
        if event is None:
            raise RuntimeError("Consul CAS conflict response drop is not armed")
        await asyncio.wait_for(event.wait(), timeout=timeout)
        self._conflict_drop_key = None
        self._conflict_response_held = None
        self._conflict_response_release = None
        self._conflict_response_dropped = None

    def write_management_value(self, key: str, value: bytes) -> None:
        """Provision a synthetic KV value with the ephemeral management token."""
        url = f"http://127.0.0.1:{self.port}/v1/kv/{quote(key, safe='/')}?dc=dc1"
        request = Request(
            url,
            data=value,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Consul-Token": self.management_token,
            },
            method="PUT",
        )
        with urlopen(request, timeout=5) as response:
            if response.status != 200 or response.read() != b"true":
                raise AssertionError("disposable Consul rejected the test KV write")

    def _bootstrap_acl_token(self) -> str:
        deadline = time.monotonic() + 45
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        self.container_name,
                        "consul",
                        "acl",
                        "bootstrap",
                        "-format=json",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                token = json.loads(result.stdout).get("SecretID")
                if not isinstance(token, str) or not token:
                    raise AssertionError("Consul ACL bootstrap omitted its token")
                return token
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                last_error = error
                time.sleep(0.5)
        raise AssertionError(
            "disposable Consul ACL bootstrap did not become ready"
        ) from last_error

    def _create_single_key_acl_token(self) -> str:
        policy_request = Request(
            f"http://127.0.0.1:{self.port}/v1/acl/policy",
            data=json.dumps(
                {
                    "Name": f"sentinel-acceptance-{uuid4().hex}",
                    "Description": "Disposable exact-key Sentinel acceptance policy",
                    "Rules": f'key "{self.key}" {{ policy = "write" }}',
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Consul-Token": self.management_token,
            },
            method="PUT",
        )
        with urlopen(policy_request, timeout=5) as response:
            policy_id = json.loads(response.read()).get("ID")
        if not isinstance(policy_id, str) or not policy_id:
            raise AssertionError("Consul did not create the exact-key test policy")

        token_request = Request(
            f"http://127.0.0.1:{self.port}/v1/acl/token",
            data=json.dumps(
                {
                    "Description": "Disposable Sentinel exact-key test token",
                    "Policies": [{"ID": policy_id}],
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Consul-Token": self.management_token,
            },
            method="PUT",
        )
        with urlopen(token_request, timeout=5) as response:
            token = json.loads(response.read()).get("SecretID")
        if not isinstance(token, str) or not token:
            raise AssertionError("Consul did not create the scoped test token")
        return token

    def _create_read_only_source_token(self) -> str:
        policy_request = Request(
            f"http://127.0.0.1:{self.port}/v1/acl/policy",
            data=json.dumps(
                {
                    "Name": f"sentinel-source-probe-{uuid4().hex}",
                    "Description": "Disposable read-only Console source-check token",
                    "Rules": 'key_prefix "" { policy = "read" }',
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Consul-Token": self.management_token,
            },
            method="PUT",
        )
        with urlopen(policy_request, timeout=5) as response:
            policy_id = json.loads(response.read()).get("ID")
        if not isinstance(policy_id, str) or not policy_id:
            raise AssertionError("Consul did not create a read-only probe policy")

        token_request = Request(
            f"http://127.0.0.1:{self.port}/v1/acl/token",
            data=json.dumps(
                {
                    "Description": "Disposable read-only Console source-check token",
                    "Policies": [{"ID": policy_id}],
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Consul-Token": self.management_token,
            },
            method="PUT",
        )
        with urlopen(token_request, timeout=5) as response:
            token = json.loads(response.read()).get("SecretID")
        if not isinstance(token, str) or not token:
            raise AssertionError("Consul did not create the read-only probe token")
        return token

    def _prepare_certificates(self) -> None:
        """Create the short-lived certificate shared by native TLS and proxy."""
        self._certificate_directory = tempfile.TemporaryDirectory(
            prefix="sentinel-consul-acl-tls-"
        )
        directory = Path(self._certificate_directory.name)
        certificate_path = directory / "certificate.pem"
        key_path = directory / "private-key.pem"
        certificate, private_key = _create_test_certificate()
        self.client_ca_pem = certificate
        certificate_path.write_text(certificate, encoding="utf-8")
        key_path.write_text(private_key, encoding="utf-8")
        self.client_ssl_context = ssl.create_default_context(cadata=certificate)

    async def _start_tls_proxy(self) -> None:
        if self._certificate_directory is None or self.client_ssl_context is None:
            self._prepare_certificates()
        directory = Path(self._certificate_directory.name)
        certificate_path = directory / "certificate.pem"
        key_path = directory / "private-key.pem"
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(
            certfile=str(certificate_path),
            keyfile=str(key_path),
        )

        async def forward(request: web.Request) -> web.Response:
            self.observed_requests.append(
                (request.raw_path, request.headers.get("X-Consul-Token"))
            )
            request_body = await request.read()
            if (
                self._pre_upstream_drop_key == request.match_info["key"]
                and request.method == "PUT"
                and request.query.get("cas") is not None
            ):
                received = self._pre_upstream_drop_received
                if received is None:
                    raise RuntimeError("pre-upstream CAS drop is incomplete")
                self._pre_upstream_drop_key = None
                received.set()
                transport = request.transport
                if transport is not None:
                    transport.close()
                return web.Response(status=200)
            if (
                self._held_cas_key == request.match_info["key"]
                and request.method == "PUT"
                and request.query.get("cas") is not None
            ):
                received = self._held_cas_received
                release = self._held_cas_release
                if received is None or release is None:
                    raise RuntimeError("Consul CAS barrier is incomplete")
                received.set()
                await release.wait()
                self._held_cas_key = None
                self._held_cas_received = None
                self._held_cas_release = None
            upstream_url = (
                f"http://127.0.0.1:{self.port}/v1/kv/{request.match_info['key']}"
            )
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
                    data=request_body,
                    allow_redirects=False,
                ) as upstream,
            ):
                response_body = await upstream.read()
                if (
                    self._response_drop_key == request.match_info["key"]
                    and request.method == "PUT"
                    and upstream.status == 200
                    and response_body == b"true"
                ):
                    committed = self._response_committed
                    release = self._response_drop_release
                    dropped = self._response_dropped
                    if committed is None or release is None or dropped is None:
                        raise RuntimeError("Consul response-loss barrier is incomplete")
                    committed.set()
                    await release.wait()
                    transport = request.transport
                    if transport is not None:
                        transport.close()
                    dropped.set()
                    return web.Response(status=200)
                if (
                    self._conflict_drop_key == request.match_info["key"]
                    and request.method == "PUT"
                    and request.query.get("cas") is not None
                    and upstream.status == 200
                    and response_body == b"false"
                ):
                    held = self._conflict_response_held
                    release = self._conflict_response_release
                    dropped = self._conflict_response_dropped
                    if held is None or release is None or dropped is None:
                        raise RuntimeError(
                            "Consul CAS conflict response drop is incomplete"
                        )
                    held.set()
                    await release.wait()
                    transport = request.transport
                    if transport is not None:
                        transport.close()
                    dropped.set()
                    return web.Response(status=200)
                response_headers = {
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower() not in excluded_headers
                }
                return web.Response(
                    status=upstream.status,
                    headers=response_headers,
                    body=response_body,
                )

        app = web.Application()
        app.router.add_route("*", "/v1/kv/{key:.*}", forward)
        self._proxy_runner = web.AppRunner(app)
        await self._proxy_runner.setup()
        site = web.TCPSite(
            self._proxy_runner, "127.0.0.1", 0, ssl_context=server_context
        )
        await site.start()
        assert site._server is not None
        self.proxy_port = site._server.sockets[0].getsockname()[1]
        self.endpoint = f"https://127.0.0.1:{self.proxy_port}"


def _create_test_certificate() -> tuple[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
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
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
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
