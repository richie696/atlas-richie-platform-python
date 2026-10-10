"""Opt-in direct-auth acceptance against isolated Nacos 3.2.4 over TLS."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from aiohttp import ClientSession, web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from atlas_richie.sentinel_console.application.check_registered_source import (
    SourceCheckAuthenticationMode,
    SourceCheckCapability,
    SourceCheckFailureReason,
    SourceConnectionInput,
)
from atlas_richie.sentinel_console.domain.configuration_source import (
    ConfigurationSourceProvider,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker_composition import (
    compose_provider_registered_source_checker,
)
from atlas_richie.sentinel_console.infrastructure.registered_source_checker import (
    RegisteredSourceTargetRule,
)

_RUN_ACCEPTANCE = (
    os.environ.get("SENTINEL_CONSOLE_RUN_NACOS_AUTH_ACCEPTANCE") == "1"
)
_NACOS_IMAGE = "nacos/nacos-server:v3.2.4"
_ADMIN_PASSWORD = "Isolated-nacos-admin-password-2026"
_TOKEN_SECRET = "VGhpc0lzTXlDb21tdW5pdHlUZXN0VG9rZW5TZWNyZXRLZXlTdHJpbmc="
_TLS_HOSTNAME = "nacos-auth.test"


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
        self._certificate_directory = None
        try:
            subprocess.run(
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
                    "127.0.0.1::8848/tcp",
                    _NACOS_IMAGE,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._started = True
            port_output = subprocess.run(
                ["docker", "port", self.container_name, "8848/tcp"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            port = int(port_output.rsplit(":", 1)[1])
            self.nacos_endpoint = f"http://127.0.0.1:{port}/nacos"
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

    async def _start_tls_proxy(self) -> None:
        certificate, private_key = _create_test_certificate()
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
            async with ClientSession(trust_env=False) as session:
                async with session.request(
                    request.method,
                    upstream_url,
                    headers=headers,
                    data=await request.read(),
                    allow_redirects=False,
                ) as upstream:
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
        site = web.TCPSite(
            self._proxy_runner, "127.0.0.1", 0, ssl_context=server_context
        )
        await site.start()
        assert site._server is not None
        self._proxy_port = site._server.sockets[0].getsockname()[1]
        self.endpoint = f"https://{_TLS_HOSTNAME}:{self._proxy_port}/nacos"

    async def _stop_tls_proxy(self) -> None:
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
            x509.SubjectAlternativeName([x509.DNSName(_TLS_HOSTNAME)]),
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


class _LoopbackResolverWithPort:
    """Resolve only the test hostname and explicitly selected ephemeral port."""

    def __init__(self, port: int) -> None:
        self._port = port

    async def __call__(self, hostname: str, port: int) -> Sequence[tuple]:
        if hostname != _TLS_HOSTNAME or port != self._port:
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


if __name__ == "__main__":
    unittest.main()
