"""ASGI protocol boundary tests for the Incident Event V1 collector route."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from atlas_richie.contracts.incidents.v1 import (
    IncidentEventReceiptV1,
    IncidentEventV1,
    IncidentSeverity,
    ResourcePressureFact,
    ResourcePressureMetric,
    encode_incident_event,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from starlette.applications import Starlette

from atlas_richie.sentinel_console.api.incident_ingest import incident_ingest_route
from atlas_richie.sentinel_console.application.incident_ingest_ports import (
    IncidentReporterBinding,
)
from atlas_richie.sentinel_console.application.ingest_incident_event import (
    IngestIncidentEvent,
)
from atlas_richie.sentinel_console.application.metrics_ingest_ports import (
    VerifiedMetricsPeer,
)

_EPOCH = UUID("71000000-0000-0000-0000-000000000001")
_INSTANT = datetime(2026, 10, 15, 4, 0, tzinfo=UTC)


class _Directory:
    def __init__(self, fingerprint: str) -> None:
        self.fingerprint = fingerprint

    async def resolve_incident_peer(self, peer: VerifiedMetricsPeer):
        if peer.certificate_sha256 != self.fingerprint:
            return None
        return IncidentReporterBinding(
            certificate_principal="spiffe://reporter.test/orders-0",
            reporter_id="reporter-orders-0",
            environment_id="test",
            app_id="orders",
            instance_id="orders-0",
            process_id="orders-pid-0",
            current_epoch=str(_EPOCH),
        )


class _History:
    def __init__(self) -> None:
        self.accepted: list[tuple[bytes, str]] = []

    async def accept_incident_event(
        self, *, event: IncidentEventV1, body: bytes, body_sha256: str, received_at, **_
    ):
        self.accepted.append((body, body_sha256))
        return IncidentEventReceiptV1(
            event_id=event.event_id,
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
    fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
    return pem, fingerprint


def _event_body() -> bytes:
    return encode_incident_event(
        IncidentEventV1(
            event_id=UUID("72000000-0000-0000-0000-000000000001"),
            process_epoch=_EPOCH,
            occurred_at=_INSTANT,
            severity=IncidentSeverity.WARNING,
            fact=ResourcePressureFact(
                metric=ResourcePressureMetric.CPU_RATIO,
                value=0.96,
                threshold=0.9,
            ),
        )
    )


async def _post(body: bytes, chain: tuple[str, ...] | None, fingerprint: str):
    history = _History()
    use_case = IngestIncidentEvent(
        _Directory(fingerprint), history, clock=lambda: _INSTANT
    )
    app = Starlette(routes=[incident_ingest_route(use_case)])
    wrapped = _TlsScope(app, chain)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wrapped), base_url="https://collector.test"
    ) as client:
        response = await client.post(
            "/api/reporting/v1/incidents",
            content=body,
            headers={"content-type": "application/json"},
        )
    return response, history


def test_valid_authenticated_reporter_gets_durable_receipt(tls_certificate):
    async def exercise():
        certificate_pem, fingerprint = tls_certificate
        body = _event_body()
        response, history = await _post(body, (certificate_pem,), fingerprint)
        assert response.status_code == 200
        assert response.json()["event_id"] == "72000000-0000-0000-0000-000000000001"
        assert response.json()["body_sha256"] == hashlib.sha256(body).hexdigest()
        assert response.json()["received_at"] == "2026-10-15T04:00:00.000000Z"
        assert history.accepted == [(body, hashlib.sha256(body).hexdigest())]

    asyncio.run(exercise())


def test_unverified_peer_and_malformed_event_are_rejected(tls_certificate):
    async def exercise():
        certificate_pem, fingerprint = tls_certificate
        anonymous, _ = await _post(_event_body(), None, fingerprint)
        malformed, history = await _post(b"{", (certificate_pem,), fingerprint)
        assert anonymous.status_code == 401
        assert anonymous.json()["error"]["code"] == "identity_not_enrolled"
        assert malformed.status_code == 400
        assert malformed.json()["error"]["code"] == "invalid_json"
        assert history.accepted == []

    asyncio.run(exercise())


def test_unknown_protocol_is_not_acknowledged(tls_certificate):
    async def exercise():
        certificate_pem, fingerprint = tls_certificate
        body = _event_body().replace(
            b"atlas-richie.incident-events/v1",
            b"atlas-richie.incident-events/v2",
        )
        response, history = await _post(body, (certificate_pem,), fingerprint)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "unsupported_protocol"
        assert history.accepted == []

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "fixture_name",
    [
        "invalid-ratio-rounding.json",
        "invalid-negative-underflow.json",
        "invalid-positive-underflow-threshold-crossing.json",
        "invalid-exponent-overflow.json",
        "invalid-max-safe-fraction.json",
        "invalid-ratio-projection-collapse.json",
        "invalid-response-projection-collapse.json",
        "invalid-resource-not-breached.json",
        "invalid-resource-below-threshold.json",
        "invalid-response-time-not-breached.json",
        "invalid-response-time-below-threshold.json",
    ],
)
def test_invalid_numeric_facts_are_never_acknowledged_or_persisted(
    fixture_name: str, tls_certificate
) -> None:
    async def exercise() -> None:
        certificate_pem, fingerprint = tls_certificate
        fixture_path = (
            Path(__file__).resolve().parents[4]
            / "foundation/contracts/tests/incidents/v1/fixtures"
            / fixture_name
        )
        body = fixture_path.read_bytes()

        response, history = await _post(body, (certificate_pem,), fingerprint)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_event"
        assert history.accepted == []

    asyncio.run(exercise())
