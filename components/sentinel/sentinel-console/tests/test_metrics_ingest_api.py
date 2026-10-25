"""ASGI contract tests for authenticated Metrics V2 snapshot ingress."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from atlas_richie.contracts.reporting.v2 import (
    CounterName,
    CounterReading,
    MetricsReceipt,
    MetricsSnapshot,
    decode_metrics_receipt,
    encode_metrics_snapshot,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from starlette.applications import Starlette

from atlas_richie.sentinel_console.api.metrics_ingest import metrics_ingest_route
from atlas_richie.sentinel_console.application.ingest_metrics import IngestMetrics
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    MetricsReporterBinding,
)


class _MemoryHistory:
    def __init__(self, binding: MetricsReporterBinding) -> None:
        self.binding = binding
        self.accepted: list[tuple[bytes, str]] = []

    async def resolve_certificate(self, certificate_sha256: str):
        if certificate_sha256 != self.binding.certificate_sha256:
            return None
        return self.binding

    async def accept_snapshot(
        self, *, binding, snapshot, body, body_sha256, received_at
    ):
        self.accepted.append((body, body_sha256))
        return MetricsReceipt(
            reporter_id=binding.reporter_id,
            startup_epoch=snapshot.startup_epoch,
            sequence=snapshot.sequence,
            body_sha256=body_sha256,
            received_at=received_at,
        )


class _TlsScope:
    def __init__(self, app, certificate_chain: tuple[str, ...] | None) -> None:
        self._app = app
        self._certificate_chain = certificate_chain

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._certificate_chain is not None:
            scope = dict(scope)
            scope["scheme"] = "https"
            scope["extensions"] = {
                "tls": {"client_cert_chain": self._certificate_chain}
            }
        await self._app(scope, receive, send)


@pytest.fixture
def tls_certificate():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "reporter.test")])
    now = datetime.now(UTC).replace(tzinfo=None)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    digest = certificate.fingerprint(hashes.SHA256()).hex()
    return pem, digest


def _snapshot_body(reporter_id: str) -> bytes:
    snapshot = MetricsSnapshot(
        reporter_id=reporter_id,
        startup_epoch=uuid4(),
        sequence=1,
        captured_at=datetime(2026, 10, 14, 1, 2, 3, tzinfo=UTC),
        capture_elapsed_ns=1_000_000_000,
        counters=(CounterReading(CounterName.HTTP_REQUESTS_COMPLETED, 1),),
    )
    return encode_metrics_snapshot(snapshot)


async def _request(body, chain, headers=None):
    if not chain:
        history = _MemoryHistory(_binding("a" * 64))
    else:
        try:
            certificate = x509.load_pem_x509_certificate(chain[0].encode("ascii"))
        except ValueError:
            history = _MemoryHistory(_binding("a" * 64))
        else:
            history = _MemoryHistory(
                _binding(certificate.fingerprint(hashes.SHA256()).hex())
            )
    app = Starlette(routes=[metrics_ingest_route(IngestMetrics(history, history))])
    wrapped = _TlsScope(app, chain)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="https://console.test"
    ) as client:
        response = await client.post(
            "/api/reporting/v2/snapshots",
            content=body,
            headers={"content-type": "application/json", **(headers or {})},
        )
    return response, history


def _binding(certificate_sha256: str) -> MetricsReporterBinding:
    return MetricsReporterBinding(
        certificate_principal="spiffe://sentinel.test/reporter/orders-1",
        certificate_sha256=certificate_sha256,
        reporter_id="reporter-orders-1",
        environment_id="test",
        app_id="orders",
        instance_id="orders-1",
        process_id="orders-1-worker-0",
    )


def test_verified_tls_peer_receives_exact_durable_receipt(tls_certificate):
    certificate_pem, certificate_sha256 = tls_certificate
    body = _snapshot_body("reporter-orders-1")

    response, history = asyncio.run(_request(body, (certificate_pem,)))

    assert response.status_code == 200
    receipt = decode_metrics_receipt(response.content)
    assert receipt.reporter_id == "reporter-orders-1"
    assert receipt.body_sha256 == hashlib.sha256(body).hexdigest()
    assert history.accepted == [(body, hashlib.sha256(body).hexdigest())]
    assert certificate_sha256 == history.binding.certificate_sha256


def test_certificate_header_cannot_substitute_for_tls_peer(tls_certificate):
    certificate_pem, _ = tls_certificate

    response, history = asyncio.run(
        _request(
            _snapshot_body("reporter-orders-1"),
            None,
            headers={"x-client-certificate": certificate_pem},
        )
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "identity_not_enrolled"
    assert history.accepted == []


def test_missing_certificate_chain_in_tls_scope_is_rejected():
    response, history = asyncio.run(_request(_snapshot_body("reporter-orders-1"), ()))

    assert response.status_code == 401
    assert history.accepted == []


def test_oversized_snapshot_is_rejected_before_ingest():
    response, history = asyncio.run(_request(b"x" * 65_537, None))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert history.accepted == []


def test_invalid_pem_certificate_is_rejected_without_header_fallback():
    response, history = asyncio.run(
        _request(
            _snapshot_body("reporter-orders-1"),
            ("not a certificate",),
            headers={"x-client-certificate": "also-not-trusted"},
        )
    )

    assert response.status_code == 401
    assert history.accepted == []
