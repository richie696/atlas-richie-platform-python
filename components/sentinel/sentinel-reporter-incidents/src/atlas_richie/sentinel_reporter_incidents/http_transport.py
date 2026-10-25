"""Verified HTTPS/mTLS Adapter for Incident Event V1 Collector ingress."""

from __future__ import annotations

import asyncio
import json
import ssl
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Protocol
from urllib.parse import urlsplit

from atlas_richie.http import (
    AsyncHttpClient,
    HttpClientOptions,
    HttpError,
    HttpRequest,
    HttpTransportError,
)

from .errors import (
    IncidentPermanentRemoteError,
    IncidentRemoteErrorCode,
    IncidentReporterError,
    IncidentReporterErrorCode,
    IncidentRetryableRemoteError,
    IncidentTransportUnavailableError,
)

_RETRYABLE_HTTP_STATUS_CODES = frozenset(
    {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_EARLY,
        HTTPStatus.TOO_MANY_REQUESTS,
    }
)
_SERVER_ERROR_STATUS_MIN = HTTPStatus.INTERNAL_SERVER_ERROR
_SERVER_ERROR_STATUS_MAX_EXCLUSIVE = 600
_REMOTE_ERROR_FIELD = "error"
_REMOTE_CODE_FIELD = "code"


@dataclass(frozen=True, slots=True)
class IncidentTlsCredential:
    """One rotating TLS context generation; SSL context is never represented."""

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


class IncidentTlsCredentialProvider(Protocol):
    """Provide the current mTLS context without exposing key material."""

    async def current(self) -> IncidentTlsCredential: ...


class _AsyncHttpClientFactory(Protocol):
    def __call__(self, options: HttpClientOptions) -> AsyncHttpClient: ...


class IncidentEventHttpTransport:
    """POST exact protocol bytes and rotate owned HTTP pools by TLS generation."""

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
        credential_provider: IncidentTlsCredentialProvider,
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
            raise ValueError("incident endpoint must be an absolute HTTPS URL")
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
        """POST a bounded event body without identity headers or redirects."""
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        async with self._lock:
            try:
                credential = await self._credential_provider.current()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - provider errors may contain key paths
                raise IncidentReporterError(
                    IncidentReporterErrorCode.CREDENTIALS_UNAVAILABLE
                ) from None
            if not isinstance(credential, IncidentTlsCredential):
                raise TypeError("credential provider returned an invalid value")
            try:
                await self._use_generation(credential)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - TLS setup errors may expose key paths
                raise IncidentReporterError(
                    IncidentReporterErrorCode.CREDENTIALS_UNAVAILABLE
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
            except asyncio.CancelledError:
                raise
            except HttpTransportError:
                raise IncidentTransportUnavailableError() from None
            except HttpError:
                raise IncidentReporterError(
                    IncidentReporterErrorCode.TRANSPORT_UNAVAILABLE
                ) from None
            if not response.is_success:
                remote_code = _remote_error_code(response.body)
                if _is_retryable_status(response.status_code):
                    raise IncidentRetryableRemoteError(
                        status_code=response.status_code,
                        remote_code=remote_code,
                    )
                raise IncidentPermanentRemoteError(
                    status_code=response.status_code,
                    remote_code=remote_code,
                )
            return response.body

    async def aclose(self) -> None:
        """Close the current pool and forget its credential generation."""
        async with self._lock:
            client = self._client
            self._client = None
            self._credential_generation = None
        if client is not None:
            await client.aclose()

    async def _use_generation(self, credential: IncidentTlsCredential) -> None:
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


def _is_retryable_status(status_code: int) -> bool:
    return (
        status_code in _RETRYABLE_HTTP_STATUS_CODES
        or int(_SERVER_ERROR_STATUS_MIN)
        <= status_code
        < _SERVER_ERROR_STATUS_MAX_EXCLUSIVE
    )


def _remote_error_code(body: bytes) -> IncidentRemoteErrorCode:
    """Read only the stable code field; response text is never retained."""
    try:
        envelope = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return IncidentRemoteErrorCode.UNKNOWN
    if not isinstance(envelope, dict):
        return IncidentRemoteErrorCode.UNKNOWN
    error = envelope.get(_REMOTE_ERROR_FIELD)
    if not isinstance(error, dict):
        return IncidentRemoteErrorCode.UNKNOWN
    code = error.get(_REMOTE_CODE_FIELD)
    if not isinstance(code, str):
        return IncidentRemoteErrorCode.UNKNOWN
    try:
        return IncidentRemoteErrorCode(code)
    except ValueError:
        return IncidentRemoteErrorCode.UNKNOWN


__all__ = [
    "IncidentEventHttpTransport",
    "IncidentTlsCredential",
    "IncidentTlsCredentialProvider",
]
