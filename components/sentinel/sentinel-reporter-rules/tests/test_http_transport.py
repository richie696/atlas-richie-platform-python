"""HTTP and mTLS boundary tests for the rule receipt adapter."""

from __future__ import annotations

import ssl
from dataclasses import dataclass

import pytest
from atlas_richie.contracts.rules.publication_receipt import (
    MAX_RULE_PUBLICATION_RECEIPT_BYTES,
)
from atlas_richie.http import HttpClientOptions, HttpResponse
from atlas_richie.sentinel_reporter_rules import (
    RulePublicationReceiptHttpTransport,
    RuleReceiptDeliveryCode,
    RuleReceiptDeliveryError,
    RuleReceiptTlsCredential,
)


@dataclass
class _ResponseSpec:
    status_code: int
    body: bytes = b""


class _FakeClient:
    def __init__(self, options: HttpClientOptions, response: _ResponseSpec) -> None:
        self.options = options
        self.response = response
        self.requests = []
        self.closed = False

    async def execute(self, request):
        self.requests.append(request)
        return HttpResponse(
            status_code=self.response.status_code,
            headers={},
            body=self.response.body,
            method=request.method,
            url=request.url,
        )

    async def aclose(self) -> None:
        self.closed = True


class _CredentialProvider:
    def __init__(self, credential: RuleReceiptTlsCredential) -> None:
        self.credential = credential

    async def current(self) -> RuleReceiptTlsCredential:
        return self.credential


def _credential(generation: str, *, verify: bool = True) -> RuleReceiptTlsCredential:
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return RuleReceiptTlsCredential(generation, context)


@pytest.mark.asyncio
async def test_transport_posts_exact_body_with_no_identity_headers() -> None:
    clients: list[_FakeClient] = []

    def create_client(options: HttpClientOptions) -> _FakeClient:
        client = _FakeClient(options, _ResponseSpec(204))
        clients.append(client)
        return client

    transport = RulePublicationReceiptHttpTransport(
        "https://collector.example/base",
        _CredentialProvider(_credential("cert-1")),
        client_factory=create_client,
    )
    payload = b'{"receipt":"exact"}'
    await transport.send(payload)

    request = clients[0].requests[0]
    assert request.url == (
        "https://collector.example/base/api/reporting/v1/rule-publication-receipts"
    )
    assert request.content == payload
    assert request.headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert clients[0].options.follow_redirects is False
    assert clients[0].options.ssl_context is not None
    await transport.aclose()
    assert clients[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 202, 400, 401, 409])
async def test_only_http_204_is_a_durable_ack(status: int) -> None:
    transport = RulePublicationReceiptHttpTransport(
        "https://collector.example",
        _CredentialProvider(_credential("cert-1")),
        client_factory=lambda options: _FakeClient(options, _ResponseSpec(status)),
    )
    with pytest.raises(RuleReceiptDeliveryError) as captured:
        await transport.send(b"{}")
    assert captured.value.code is RuleReceiptDeliveryCode.PERMANENT_REMOTE
    assert str(captured.value) == "permanent_remote"
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
async def test_retryable_collector_status_is_classified(status: int) -> None:
    transport = RulePublicationReceiptHttpTransport(
        "https://collector.example",
        _CredentialProvider(_credential("cert-1")),
        client_factory=lambda options: _FakeClient(options, _ResponseSpec(status)),
    )
    with pytest.raises(RuleReceiptDeliveryError) as captured:
        await transport.send(b"{}")
    assert captured.value.retryable
    assert captured.value.code is RuleReceiptDeliveryCode.RETRYABLE_REMOTE
    await transport.aclose()


@pytest.mark.asyncio
async def test_credential_generation_rotation_replaces_and_closes_pool() -> None:
    clients: list[_FakeClient] = []
    credentials = _CredentialProvider(_credential("cert-1"))

    def create_client(options: HttpClientOptions) -> _FakeClient:
        client = _FakeClient(options, _ResponseSpec(204))
        clients.append(client)
        return client

    transport = RulePublicationReceiptHttpTransport(
        "https://collector.example", credentials, client_factory=create_client
    )
    await transport.send(b"first")
    credentials.credential = _credential("cert-2")
    await transport.send(b"second")

    assert len(clients) == 2
    assert clients[0].closed
    assert not clients[1].closed
    await transport.aclose()
    assert clients[1].closed


@pytest.mark.asyncio
async def test_oversize_payload_is_rejected_before_credentials_or_network() -> None:
    class UnusedProvider:
        async def current(self):
            pytest.fail("credential lookup must not happen for oversized payload")

    transport = RulePublicationReceiptHttpTransport(
        "https://collector.example",
        UnusedProvider(),
        client_factory=lambda options: pytest.fail("client must not be created"),
    )
    with pytest.raises(ValueError, match="protocol size limit"):
        await transport.send(b"x" * (MAX_RULE_PUBLICATION_RECEIPT_BYTES + 1))
    await transport.aclose()


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://collector.example",
        "https://user:secret@collector.example",
        "https://collector.example?token=secret",
        "https://collector.example/#secret",
        "relative/path",
    ],
)
def test_endpoint_requires_clean_absolute_https_base_url(endpoint: str) -> None:
    with pytest.raises(ValueError, match="absolute HTTPS"):
        RulePublicationReceiptHttpTransport(
            endpoint, _CredentialProvider(_credential("x"))
        )


def test_tls_credential_requires_server_validation() -> None:
    context = ssl.create_default_context()
    context.check_hostname = False
    with pytest.raises(ValueError, match="hostname"):
        RuleReceiptTlsCredential("invalid", context)


def test_transport_validates_credential_provider_and_timeout_types() -> None:
    with pytest.raises(TypeError, match="credential_provider"):
        RulePublicationReceiptHttpTransport("https://collector.example", object())
    with pytest.raises(TypeError, match="HttpTimeout"):
        RulePublicationReceiptHttpTransport(
            "https://collector.example",
            _CredentialProvider(_credential("valid")),
            timeout=1,  # type: ignore[arg-type]
        )
