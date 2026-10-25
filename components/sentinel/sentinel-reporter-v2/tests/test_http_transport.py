import json
import socket
import ssl
import subprocess
import tempfile
import threading
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

import pytest
from atlas_richie.contracts.reporting.v2 import (
    MetricsReceipt,
    decode_metrics_snapshot,
    encode_metrics_receipt,
)
from atlas_richie.http import HttpResponse
from atlas_richie.sentinel_reporter_v2 import (
    MetricsReporterErrorCode,
    MetricsTransportError,
    MetricsV2HttpTransport,
    MetricsV2TlsCredential,
)

_EPOCH = UUID("7aaafa02-b778-40bc-b516-e008f25a19ef")


class _Provider:
    def __init__(self, credentials):
        self.credentials = list(credentials)

    async def current(self):
        return self.credentials.pop(0)


class _Client:
    def __init__(self):
        self.requests = []
        self.closed = False

    async def execute(self, request):
        self.requests.append(request)
        snapshot = decode_metrics_snapshot(request.content)
        receipt = MetricsReceipt(
            snapshot.reporter_id,
            snapshot.startup_epoch,
            snapshot.sequence,
            sha256(request.content).hexdigest(),
            snapshot.captured_at,
        )
        return HttpResponse(
            200,
            {"Content-Type": "application/json"},
            encode_metrics_receipt(receipt),
            request.method,
            request.url,
        )

    async def aclose(self):
        self.closed = True


class _RateLimitedClient(_Client):
    async def execute(self, request):
        self.requests.append(request)
        return HttpResponse(
            429,
            {"Retry-After": "120"},
            b"private collector detail",
            request.method,
            request.url,
        )


def _credential(generation: str):
    return MetricsV2TlsCredential(generation, ssl.create_default_context())


def _payload() -> bytes:
    from datetime import UTC, datetime

    from atlas_richie.contracts.reporting.v2 import (
        GaugeName,
        GaugeQuality,
        GaugeReading,
        MetricsSnapshot,
        encode_metrics_snapshot,
    )

    return encode_metrics_snapshot(
        MetricsSnapshot(
            reporter_id="reporter-a",
            startup_epoch=_EPOCH,
            sequence=1,
            captured_at=datetime(2026, 10, 14, tzinfo=UTC),
            capture_elapsed_ns=1,
            gauges=(
                GaugeReading(
                    GaugeName.PROCESS_CPU_RATIO, None, GaugeQuality.UNAVAILABLE
                ),
            ),
        )
    )


@pytest.mark.asyncio
async def test_tls_generation_rotation_replaces_pool_without_identity_headers() -> None:
    first = _credential("certificate-1")
    second = _credential("certificate-2")
    provider = _Provider([first, second])
    clients = []
    options_seen = []

    def create_client(options):
        options_seen.append(options)
        client = _Client()
        clients.append(client)
        return client

    transport = MetricsV2HttpTransport(
        "https://collector.example.test/api/v2/metrics",
        provider,
        client_factory=create_client,
    )
    payload = _payload()

    assert await transport.send(payload)
    assert await transport.send(payload)

    assert len(clients) == 2
    assert clients[0].closed is True
    assert options_seen[0].ssl_context is first.ssl_context
    assert options_seen[1].ssl_context is second.ssl_context
    for client in clients:
        request = client.requests[0]
        assert request.content == payload
        assert "Authorization" not in request.headers
        assert "X-Atlas-Reporter-Id" not in request.headers
        assert request.headers["Content-Type"] == "application/json"
    await transport.aclose()
    assert clients[1].closed is True


def test_transport_rejects_plain_http_and_insecure_tls_context() -> None:
    provider = _Provider([])
    with pytest.raises(ValueError, match="absolute HTTPS"):
        MetricsV2HttpTransport("http://collector.example.test/metrics", provider)

    insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="require server certificate"):
        MetricsV2TlsCredential("insecure", insecure)


@pytest.mark.asyncio
async def test_rate_limit_is_a_redacted_retryable_transport_failure() -> None:
    client = _RateLimitedClient()
    transport = MetricsV2HttpTransport(
        "https://collector.example.test/api/v2/metrics",
        _Provider([_credential("certificate-1")]),
        client_factory=lambda _options: client,
    )

    with pytest.raises(MetricsTransportError) as error:
        await transport.send(_payload())

    assert error.value.code is MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE
    assert str(error.value) == "transport_unavailable"
    assert "private collector detail" not in str(error.value)
    assert len(client.requests) == 1
    await transport.aclose()


@pytest.mark.asyncio
async def test_credential_provider_errors_and_context_repr_do_not_leak_secrets() -> (
    None
):
    credential = _credential("certificate-1")
    assert "SSLContext" not in repr(credential)

    provider = _Provider([])

    async def fail_with_secret():
        raise RuntimeError("private-key=/secrets/reporter.key")

    provider.current = fail_with_secret
    transport = MetricsV2HttpTransport(
        "https://collector.example.test/api/v2/metrics",
        provider,
        client_factory=lambda _options: _Client(),
    )
    with pytest.raises(MetricsTransportError) as error:
        await transport.send(_payload())
    assert str(error.value) == "credentials_unavailable"
    assert "/secrets/reporter.key" not in str(error.value)


@pytest.mark.asyncio
async def test_connection_refusal_is_redacted_as_retryable_transport_failure() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        unused_port = probe.getsockname()[1]

    transport = MetricsV2HttpTransport(
        f"https://127.0.0.1:{unused_port}/metrics",
        _Provider([_credential("certificate-1")]),
    )
    with pytest.raises(MetricsTransportError) as error:
        await transport.send(_payload())
    assert error.value.code is MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE
    assert str(error.value) == "transport_unavailable"
    assert f"{unused_port}" not in str(error.value)
    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_performs_real_mutual_tls_and_verifies_collector_certificate() -> (
    None
):
    with tempfile.TemporaryDirectory(prefix="metrics-v2-mtls-") as temp_directory:
        root = Path(temp_directory)
        _create_test_certificates(root)
        peer_certificates = []
        transport = None

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                peer_certificates.append(self.connection.getpeercert())
                size = int(self.headers["Content-Length"])
                request_body = self.rfile.read(size)
                snapshot = decode_metrics_snapshot(request_body)
                receipt = MetricsReceipt(
                    snapshot.reporter_id,
                    snapshot.startup_epoch,
                    snapshot.sequence,
                    sha256(request_body).hexdigest(),
                    snapshot.captured_at,
                )
                response_body = encode_metrics_receipt(receipt)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, _format, *_args):
                return

        server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        server_context.load_cert_chain(root / "server.pem", root / "server.key")
        server_context.load_verify_locations(root / "ca.pem")
        server_context.verify_mode = ssl.CERT_REQUIRED
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client_context = ssl.create_default_context(cafile=root / "ca.pem")
            client_context.load_cert_chain(root / "client.pem", root / "client.key")
            transport = MetricsV2HttpTransport(
                f"https://127.0.0.1:{server.server_port}/metrics",
                _Provider([MetricsV2TlsCredential("fixture-cert-1", client_context)]),
            )
            payload = _payload()
            ack = await transport.send(payload)
            decoded = decode_metrics_snapshot(payload)
            assert json.loads(ack)["sequence"] == decoded.sequence
            assert peer_certificates and peer_certificates[0]
        finally:
            if transport is not None:
                await transport.aclose()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def _create_test_certificates(directory: Path) -> None:
    """Create ephemeral CA/server/client identities for the local TLS test."""
    ca_key = directory / "ca.key"
    ca_certificate = directory / "ca.pem"
    subprocess.run(
        (
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_certificate),
            "-days",
            "1",
            "-subj",
            "/CN=Metrics V2 Test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ),
        check=True,
        capture_output=True,
        text=True,
    )

    for name, common_name in (("server", "127.0.0.1"), ("client", "reporter-a")):
        subprocess.run(
            (
                "openssl",
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(directory / f"{name}.key"),
                "-out",
                str(directory / f"{name}.csr"),
                "-subj",
                f"/CN={common_name}",
            ),
            check=True,
            capture_output=True,
            text=True,
        )

    for name, extensions in (
        (
            "server",
            (
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n"
                "subjectAltName=IP:127.0.0.1\n"
            ),
        ),
        (
            "client",
            (
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=clientAuth\n"
            ),
        ),
    ):
        extension_file = directory / f"{name}-ext.cnf"
        extension_file.write_text(f"[v3_ext]\n{extensions}", encoding="ascii")
        subprocess.run(
            (
                "openssl",
                "x509",
                "-req",
                "-in",
                str(directory / f"{name}.csr"),
                "-CA",
                str(ca_certificate),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(directory / f"{name}.pem"),
                "-days",
                "1",
                "-extfile",
                str(extension_file),
                "-extensions",
                "v3_ext",
            ),
            check=True,
            capture_output=True,
            text=True,
        )
