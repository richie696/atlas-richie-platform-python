"""Verified HTTPS/mTLS adapter for Rule Publication Receipt V1 ingress."""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from atlas_richie.contracts.rules.publication_receipt import (
    MAX_RULE_PUBLICATION_RECEIPT_BYTES,
)
from atlas_richie.http import (
    AsyncHttpClient,
    HttpClientOptions,
    HttpError,
    HttpRequest,
    HttpTimeout,
    HttpTransportError,
)

from .errors import RuleReceiptDeliveryCode, RuleReceiptDeliveryError

_INGRESS_PATH = "/api/reporting/v1/rule-publication-receipts"
_MAX_ACK_RESPONSE_BYTES = 4096
_SERVER_ERROR_STATUS_MAX_EXCLUSIVE = 600
_RETRYABLE_STATUSES = frozenset(
    {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_EARLY,
        HTTPStatus.TOO_MANY_REQUESTS,
    }
)


@dataclass(frozen=True, slots=True)
class RuleReceiptTlsCredential:
    """One rotating client-authenticated TLS context generation."""

    generation: str
    ssl_context: ssl.SSLContext = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.generation, str) or not self.generation.strip():
            raise ValueError("TLS credential generation must be non-blank")
        if not isinstance(self.ssl_context, ssl.SSLContext):
            raise TypeError("ssl_context must be ssl.SSLContext")
        if self.ssl_context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS context must require server certificate validation")
        if not self.ssl_context.check_hostname:
            raise ValueError("TLS context must validate the server hostname")


class RuleReceiptTlsCredentialProvider(Protocol):
    """Resolve the current mTLS credential without exposing key material."""

    async def current(self) -> RuleReceiptTlsCredential: ...


class _AsyncHttpClientFactory(Protocol):
    """Create an HTTP client configured for one credential."""

    def __call__(self, options: HttpClientOptions) -> AsyncHttpClient: ...


class RulePublicationReceiptHttpTransport:
    """Send exact bytes and accept only Collector HTTP 204 as durable ACK."""

    __slots__ = (
        "_client",
        "_client_factory",
        "_credential_generation",
        "_credential_provider",
        "_endpoint_url",
        "_lock",
        "_timeout",
    )

    def __init__(
        self,
        endpoint_url: str,
        credential_provider: RuleReceiptTlsCredentialProvider,
        *,
        client_factory: _AsyncHttpClientFactory = AsyncHttpClient,
        timeout: HttpTimeout | None = None,
    ) -> None:
        parsed = urlsplit(endpoint_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("receipt endpoint must be an absolute HTTPS base URL")
        if not callable(client_factory):
            raise TypeError("client_factory must be callable")
        if not callable(getattr(credential_provider, "current", None)):
            raise TypeError("credential_provider must provide current()")
        if timeout is not None and not isinstance(timeout, HttpTimeout):
            raise TypeError("timeout must be HttpTimeout or None")
        self._endpoint_url = (
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
            + _INGRESS_PATH
        )
        self._credential_provider = credential_provider
        self._client_factory = client_factory
        self._timeout = timeout or HttpTimeout()
        self._credential_generation: str | None = None
        self._client: AsyncHttpClient | None = None
        self._lock = asyncio.Lock()

    async def send(self, payload: bytes) -> None:
        """POST one bounded protocol body using the current credential."""
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if len(payload) > MAX_RULE_PUBLICATION_RECEIPT_BYTES:
            raise ValueError("receipt body exceeds the protocol size limit")
        async with self._lock:
            credential = await self._current_credential()
            await self._use_generation(credential)
            assert self._client is not None
            request = HttpRequest(
                method="POST",
                url=self._endpoint_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=payload,
                timeout=self._timeout,
            )
            try:
                response = await self._client.execute(request)
            except asyncio.CancelledError:
                raise
            except HttpTransportError:
                raise RuleReceiptDeliveryError(
                    RuleReceiptDeliveryCode.TRANSPORT_UNAVAILABLE, retryable=True
                ) from None
            except HttpError:
                raise RuleReceiptDeliveryError(
                    RuleReceiptDeliveryCode.TRANSPORT_UNAVAILABLE, retryable=False
                ) from None
            if response.status_code == HTTPStatus.NO_CONTENT:
                return
            retryable = (
                response.status_code in _RETRYABLE_STATUSES
                or HTTPStatus.INTERNAL_SERVER_ERROR
                <= response.status_code
                < _SERVER_ERROR_STATUS_MAX_EXCLUSIVE
            )
            raise RuleReceiptDeliveryError(
                RuleReceiptDeliveryCode.RETRYABLE_REMOTE
                if retryable
                else RuleReceiptDeliveryCode.PERMANENT_REMOTE,
                retryable=retryable,
            )

    async def aclose(self) -> None:
        """Close the current HTTP pool and forget its TLS generation."""
        async with self._lock:
            client = self._client
            self._client = None
            self._credential_generation = None
        if client is not None:
            await client.aclose()

    async def _current_credential(self) -> RuleReceiptTlsCredential:
        try:
            credential = await self._credential_provider.current()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider errors may contain key paths
            raise RuleReceiptDeliveryError(
                RuleReceiptDeliveryCode.CREDENTIALS_UNAVAILABLE, retryable=True
            ) from None
        if not isinstance(credential, RuleReceiptTlsCredential):
            raise TypeError("credential provider returned an invalid value")
        return credential

    async def _use_generation(self, credential: RuleReceiptTlsCredential) -> None:
        if credential.generation == self._credential_generation:
            return
        try:
            replacement = self._client_factory(
                HttpClientOptions(
                    ssl_context=credential.ssl_context,
                    timeout=self._timeout,
                    max_response_bytes=_MAX_ACK_RESPONSE_BYTES,
                    follow_redirects=False,
                    headers={},
                )
            )
        except Exception:  # noqa: BLE001 - setup errors can expose filesystem paths
            raise RuleReceiptDeliveryError(
                RuleReceiptDeliveryCode.CREDENTIALS_UNAVAILABLE, retryable=True
            ) from None
        previous = self._client
        self._client = replacement
        self._credential_generation = credential.generation
        if previous is not None:
            await previous.aclose()


__all__ = [
    "RulePublicationReceiptHttpTransport",
    "RuleReceiptTlsCredential",
    "RuleReceiptTlsCredentialProvider",
]
