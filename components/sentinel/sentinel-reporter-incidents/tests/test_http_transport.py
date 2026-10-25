from __future__ import annotations

import ssl

import pytest
from atlas_richie.http import HttpResponse

from atlas_richie.sentinel_reporter_incidents import (
    IncidentEventHttpTransport,
    IncidentPermanentRemoteError,
    IncidentRemoteErrorCode,
    IncidentReporterError,
    IncidentReporterErrorCode,
    IncidentRetryableRemoteError,
    IncidentTlsCredential,
    IncidentTransportUnavailableError,
)


class _Provider:
    def __init__(self, credentials: list[IncidentTlsCredential]) -> None:
        self.credentials = list(credentials)

    async def current(self) -> IncidentTlsCredential:
        return self.credentials.pop(0)


class _Client:
    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self.body = body
        self.status = status
        self.requests = []
        self.closed = False

    async def execute(self, request):
        self.requests.append(request)
        return HttpResponse(
            self.status,
            {},
            self.body,
            request.method,
            request.url,
        )

    async def aclose(self) -> None:
        self.closed = True


def _credential(generation: str) -> IncidentTlsCredential:
    return IncidentTlsCredential(generation, ssl.create_default_context())


@pytest.mark.asyncio
async def test_transport_posts_exact_body_and_rotates_owned_tls_pool() -> None:
    first, second = _credential("cert-1"), _credential("cert-2")
    provider = _Provider([first, second])
    clients: list[_Client] = []
    options_seen = []

    def client_factory(options):
        options_seen.append(options)
        client = _Client(b"durable-ack")
        clients.append(client)
        return client

    transport = IncidentEventHttpTransport(
        "https://collector.example.test/api/reporting/v1/incidents",
        provider,
        client_factory=client_factory,
    )
    assert await transport.send(b'{"event":1}') == b"durable-ack"
    assert await transport.send(b'{"event":1}') == b"durable-ack"
    await transport.aclose()

    assert len(clients) == 2
    assert clients[0].closed is True
    assert clients[1].closed is True
    assert options_seen[0].ssl_context is first.ssl_context
    assert options_seen[1].ssl_context is second.ssl_context
    for client in clients:
        request = client.requests[0]
        assert request.method == "POST"
        assert request.content == b'{"event":1}'
        assert request.headers["Content-Type"] == "application/json"
        assert "Authorization" not in request.headers
        assert "X-Atlas-Reporter-Id" not in request.headers


@pytest.mark.asyncio
async def test_transport_redacts_http_failures() -> None:
    clients: list[_Client] = []

    def client_factory(_options):
        client = _Client(b"private response text", status=503)
        clients.append(client)
        return client

    transport = IncidentEventHttpTransport(
        "https://collector.example.test/api/reporting/v1/incidents",
        _Provider([_credential("cert-1")]),
        client_factory=client_factory,
    )

    with pytest.raises(IncidentReporterError) as raised:
        await transport.send(b"{}")

    assert isinstance(raised.value, IncidentRetryableRemoteError)
    assert raised.value.status_code == 503
    assert raised.value.remote_code is IncidentRemoteErrorCode.UNKNOWN
    assert "private response" not in str(raised.value)
    await transport.aclose()


@pytest.mark.parametrize(
    ("status", "body", "error_type", "remote_code"),
    [
        (
            408,
            b'{"error":{"code":"service_unavailable"}}',
            IncidentRetryableRemoteError,
            IncidentRemoteErrorCode.SERVICE_UNAVAILABLE,
        ),
        (
            425,
            b'{"error":{"code":"invalid_request"}}',
            IncidentRetryableRemoteError,
            IncidentRemoteErrorCode.INVALID_REQUEST,
        ),
        (
            429,
            b'{"error":{"code":"rate_limited"}}',
            IncidentRetryableRemoteError,
            IncidentRemoteErrorCode.RATE_LIMITED,
        ),
        (
            500,
            b'{"error":{"code":"storage_unavailable"}}',
            IncidentRetryableRemoteError,
            IncidentRemoteErrorCode.STORAGE_UNAVAILABLE,
        ),
        (
            503,
            b'{"error":{"code":"service_unavailable"}}',
            IncidentRetryableRemoteError,
            IncidentRemoteErrorCode.SERVICE_UNAVAILABLE,
        ),
        (
            400,
            b'{"error":{"code":"invalid_request"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.INVALID_REQUEST,
        ),
        (
            400,
            b'{"error":{"code":"invalid_json"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.INVALID_JSON,
        ),
        (
            400,
            b'{"error":{"code":"unsupported_protocol"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.UNSUPPORTED_PROTOCOL,
        ),
        (
            400,
            b'{"error":{"code":"invalid_event"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.INVALID_EVENT,
        ),
        (
            401,
            b'{"error":{"code":"identity_not_enrolled"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.IDENTITY_NOT_ENROLLED,
        ),
        (
            409,
            b'{"error":{"code":"idempotency_conflict"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.IDEMPOTENCY_CONFLICT,
        ),
        (
            413,
            b'{"error":{"code":"payload_too_large"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.PAYLOAD_TOO_LARGE,
        ),
        (
            415,
            b'{"error":{"code":"invalid_content_type"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.INVALID_CONTENT_TYPE,
        ),
        (
            409,
            b'{"error":{"code":"private-db-detail"}}',
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.UNKNOWN,
        ),
        (
            409,
            b"not-json private-body",
            IncidentPermanentRemoteError,
            IncidentRemoteErrorCode.UNKNOWN,
        ),
    ],
)
@pytest.mark.asyncio
async def test_transport_maps_http_status_to_typed_redacted_remote_error(
    status, body, error_type, remote_code
) -> None:
    client = _Client(body, status)
    secret_url = "https://collector.example.test/events?token=private"
    transport = IncidentEventHttpTransport(
        secret_url,
        _Provider([_credential("cert-1")]),
        client_factory=lambda _options: client,
    )

    with pytest.raises(error_type) as raised:
        await transport.send(b'{"private-event":"body"}')

    assert raised.value.status_code == status
    assert raised.value.remote_code is remote_code
    assert raised.value.retryable is (error_type is IncidentRetryableRemoteError)
    rendered_error = f"{raised.value!s} {raised.value!r}"
    for secret in (
        "private-db-detail",
        "not-json",
        "token=private",
        "private-event",
    ):
        assert secret not in rendered_error
    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_classifies_network_failure_as_retryable_without_details() -> (
    None
):
    with pytest.raises(IncidentTransportUnavailableError) as raised:
        transport = IncidentEventHttpTransport(
            "https://127.0.0.1:1/events",
            _Provider([_credential("cert-1")]),
        )
        await transport.send(b"{}")
    assert raised.value.code is IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE
    assert "127.0.0.1" not in str(raised.value)
    await transport.aclose()


def test_transport_requires_verified_https_and_valid_mtls_credential() -> None:
    with pytest.raises(ValueError, match="absolute HTTPS"):
        IncidentEventHttpTransport("http://collector.test/events", _Provider([]))
    insecure = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="server certificate"):
        IncidentTlsCredential("insecure", insecure)
