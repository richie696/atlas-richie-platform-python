"""HTTPS/mTLS Reporter Adapter using the owned ``atlas-richie-http`` client."""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from atlas_richie.http import AsyncHttpClient, HttpClientOptions, HttpError, HttpRequest

from .errors import MetricsReporterErrorCode, MetricsTransportError


@dataclass(frozen=True, slots=True)
class MetricsV2TlsCredential:
    """One verified TLS context generation; the context never enters repr/logs."""

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


class MetricsV2TlsCredentialProvider(Protocol):
    """Supply the current TLS identity generation without exposing key bytes."""

    async def current(self) -> MetricsV2TlsCredential: ...


class _AsyncHttpClientFactory(Protocol):
    def __call__(self, options: HttpClientOptions) -> AsyncHttpClient: ...


class MetricsV2HttpTransport:
    """Send snapshots over verified HTTPS and rotate pooled TLS identity safely.

    No bearer token or client-asserted identity header is emitted. Reporter
    identity is checked by the Collector against the authenticated mTLS peer.
    The transport is sequential by design; switching credential generation
    creates a new verified client pool before retiring the previous pool.
    """

    __slots__ = (
        "_client",
        "_client_factory",
        "_credential_generation",
        "_credential_provider",
        "_endpoint_url",
        "_lock",
        "_max_response_bytes",
    )

    def __init__(
        self,
        endpoint_url: str,
        credential_provider: MetricsV2TlsCredentialProvider,
        *,
        client_factory: _AsyncHttpClientFactory = AsyncHttpClient,
        max_response_bytes: int = 4096,
    ) -> None:
        parsed = urlsplit(endpoint_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("Metrics V2 endpoint must be an absolute HTTPS URL")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 65_536:
            raise ValueError("max_response_bytes must be between 1 and 65536")
        self._endpoint_url = endpoint_url
        self._credential_provider = credential_provider
        self._client_factory = client_factory
        self._max_response_bytes = max_response_bytes
        self._credential_generation: str | None = None
        self._client: AsyncHttpClient | None = None
        self._lock = asyncio.Lock()

    async def send(self, payload: bytes) -> bytes:
        """POST exact V2 bytes; non-2xx responses propagate as transport errors."""
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        async with self._lock:
            try:
                credential = await self._credential_provider.current()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - redact credential-provider detail
                raise MetricsTransportError(
                    MetricsReporterErrorCode.CREDENTIALS_UNAVAILABLE
                ) from None
            if not isinstance(credential, MetricsV2TlsCredential):
                raise TypeError("credential provider returned an invalid value")
            try:
                await self._use_generation(credential)
            except Exception:  # noqa: BLE001 - TLS setup details may contain local secrets
                raise MetricsTransportError(
                    MetricsReporterErrorCode.CREDENTIALS_UNAVAILABLE
                ) from None
            assert self._client is not None
            request = HttpRequest(
                method="POST",
                url=self._endpoint_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                content=payload,
            )
            try:
                response = await self._client.execute(request)
                response.require_success()
            except asyncio.CancelledError:
                raise
            except HttpError:
                raise MetricsTransportError(
                    MetricsReporterErrorCode.TRANSPORT_UNAVAILABLE
                ) from None
            return response.body

    async def aclose(self) -> None:
        """Close the current owned client pool and forget its certificate epoch."""
        async with self._lock:
            client = self._client
            self._client = None
            self._credential_generation = None
        if client is not None:
            await client.aclose()

    async def _use_generation(self, credential: MetricsV2TlsCredential) -> None:
        if credential.generation == self._credential_generation:
            return
        replacement = self._client_factory(
            HttpClientOptions(
                ssl_context=credential.ssl_context,
                max_response_bytes=self._max_response_bytes,
                follow_redirects=False,
                headers={},
            )
        )
        previous = self._client
        self._client = replacement
        self._credential_generation = credential.generation
        if previous is not None:
            await previous.aclose()


__all__ = [
    "MetricsV2HttpTransport",
    "MetricsV2TlsCredential",
    "MetricsV2TlsCredentialProvider",
]
