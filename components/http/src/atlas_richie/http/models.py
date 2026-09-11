"""Portable HTTP request, response, and client-option values."""

from __future__ import annotations

import json
from secrets import token_hex
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from .errors import HttpDecodeError, HttpStatusError, HttpStreamClosedError


class HttpMethod(StrEnum):
    """Standard request methods offered as named request constructors."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class MediaType(StrEnum):
    """Media types with first-class request construction semantics."""

    JSON = "application/json"
    XML = "application/xml"
    SOAP_12 = "application/soap+xml"
    FORM = "application/x-www-form-urlencoded"
    MULTIPART_FORM = "multipart/form-data"
    EVENT_STREAM = "text/event-stream"


_UTF_8 = "utf-8"
_CONTENT_TYPE_HEADER = "Content-Type"
_SOAP_ACTION_HEADER = "SOAPAction"
_FORM_CONTENT_TYPE = f"{MediaType.FORM}; charset={_UTF_8}"
_JSON_CONTENT_TYPE = f"{MediaType.JSON}; charset={_UTF_8}"
_XML_CONTENT_TYPE = f"{MediaType.XML}; charset={_UTF_8}"
_SOAP_CONTENT_TYPE = f"{MediaType.SOAP_12}; charset={_UTF_8}"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_READ_TIMEOUT_SECONDS = 20.0
DEFAULT_WRITE_TIMEOUT_SECONDS = 20.0
DEFAULT_POOL_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
SUCCESS_STATUS_MIN = 200
SUCCESS_STATUS_EXCLUSIVE_MAX = 300
DEFAULT_MULTIPART_BOUNDARY_BYTES = 16
_UNSET = object()


def _freeze_headers(headers: Mapping[str, str] | None) -> Mapping[str, str]:
    values = dict(headers or {})
    if any(not isinstance(name, str) or not isinstance(value, str) for name, value in values.items()):
        raise TypeError("HTTP headers must map strings to strings")
    return MappingProxyType(values)


def header_value(headers: Mapping[str, str], name: str) -> str | None:
    """Return a header value with HTTP's case-insensitive name matching."""

    expected = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == expected), None)


def with_header(headers: Mapping[str, str], name: str, value: str) -> Mapping[str, str]:
    """Return a new immutable mapping, replacing an existing case-insensitive header."""

    values = {key: existing for key, existing in headers.items() if key.casefold() != name.casefold()}
    values[name] = value
    return MappingProxyType(values)


def _text_pairs(
    values: Mapping[str, str] | Sequence[tuple[str, str]],
    *,
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    pairs = tuple(values.items()) if isinstance(values, Mapping) else tuple(values)
    if any(not isinstance(key, str) or not key or not isinstance(value, str) for key, value in pairs):
        raise TypeError(f"{field_name} must contain non-empty string keys and string values")
    return pairs


def _with_content_type(headers: Mapping[str, str], value: str) -> Mapping[str, str]:
    return headers if header_value(headers, _CONTENT_TYPE_HEADER) else with_header(headers, _CONTENT_TYPE_HEADER, value)


@dataclass(frozen=True, slots=True)
class MultipartPart:
    """One immutable multipart/form-data part; file-like streams stay application-owned."""

    name: str
    content: bytes
    filename: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.name or "\r" in self.name or "\n" in self.name:
            raise ValueError("multipart part name must be non-empty and header-safe")
        if not isinstance(self.content, bytes):
            raise TypeError("multipart content must be bytes")
        for value, label in ((self.filename, "filename"), (self.media_type, "media_type")):
            if value is not None and (not value or "\r" in value or "\n" in value):
                raise ValueError(f"multipart {label} must be non-empty and header-safe when present")


@dataclass(frozen=True, slots=True)
class HttpTimeout:
    """Explicit per-operation timeout budget in seconds."""

    connect: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read: float = DEFAULT_READ_TIMEOUT_SECONDS
    write: float = DEFAULT_WRITE_TIMEOUT_SECONDS
    pool: float = DEFAULT_POOL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if any(value <= 0 for value in (self.connect, self.read, self.write, self.pool)):
            raise ValueError("all timeout values must be positive")


@dataclass(frozen=True, slots=True)
class HttpClientOptions:
    """Client-wide limits and secure defaults owned by the component."""

    timeout: HttpTimeout = field(default_factory=HttpTimeout)
    max_connections: int = DEFAULT_MAX_CONNECTIONS
    max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE_CONNECTIONS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    follow_redirects: bool = False
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_connections <= 0 or self.max_keepalive_connections < 0:
            raise ValueError("connection limits must be non-negative and max_connections positive")
        if self.max_keepalive_connections > self.max_connections:
            raise ValueError("max_keepalive_connections cannot exceed max_connections")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        object.__setattr__(self, "headers", _freeze_headers(self.headers))


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """An immutable outbound HTTP request with no transport-library types."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    content: bytes | None = None
    timeout: HttpTimeout | None = None
    query: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        method = self.method.upper().strip()
        if not method or any(character.isspace() for character in method):
            raise ValueError("HTTP method must be a single non-empty token")
        if not self.url.strip():
            raise ValueError("HTTP URL must not be blank")
        if self.content is not None and not isinstance(self.content, bytes):
            raise TypeError("HTTP content must be bytes or None")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "headers", _freeze_headers(self.headers))
        object.__setattr__(self, "query", _text_pairs(self.query, field_name="query parameters"))

    @classmethod
    def get(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        return cls(HttpMethod.GET, url, headers or {})

    @classmethod
    def post(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        return cls(HttpMethod.POST, url, headers or {})

    @classmethod
    def put(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        return cls(HttpMethod.PUT, url, headers or {})

    @classmethod
    def patch(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        return cls(HttpMethod.PATCH, url, headers or {})

    @classmethod
    def delete(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        return cls(HttpMethod.DELETE, url, headers or {})

    @classmethod
    def json(
        cls,
        method: str,
        url: str,
        value: Any,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> "HttpRequest":
        return cls(method, url, headers or {}).with_json(value)

    def with_header(self, name: str, value: str) -> "HttpRequest":
        return self._replace(headers=with_header(self.headers, name, value))

    def with_headers(self, headers: Mapping[str, str]) -> "HttpRequest":
        result = self
        for name, value in headers.items():
            result = result.with_header(name, value)
        return result

    def with_query_param(self, name: str, value: str) -> "HttpRequest":
        return self._replace(query=(*self.query, *_text_pairs(((name, value),), field_name="query parameters")))

    def with_query_params(self, values: Mapping[str, str] | Sequence[tuple[str, str]]) -> "HttpRequest":
        return self._replace(query=(*self.query, *_text_pairs(values, field_name="query parameters")))

    def with_timeout(self, timeout: HttpTimeout) -> "HttpRequest":
        if not isinstance(timeout, HttpTimeout):
            raise TypeError("timeout must be an HttpTimeout")
        return self._replace(timeout=timeout)

    def with_content(self, content: bytes | None, *, media_type: str | None = None) -> "HttpRequest":
        if media_type is not None and (not isinstance(media_type, str) or not media_type.strip()):
            raise ValueError("media_type must be a non-blank string when present")
        headers = _with_content_type(self.headers, media_type) if media_type else self.headers
        return self._replace(headers=headers, content=content)

    def with_json(self, value: Any) -> "HttpRequest":
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(_UTF_8)
        return self.with_content(content, media_type=_JSON_CONTENT_TYPE)

    def with_xml(self, value: str) -> "HttpRequest":
        return self._with_text_content(value, _XML_CONTENT_TYPE)

    def with_soap(self, envelope: str, *, action: str | None = None) -> "HttpRequest":
        request = self._with_text_content(envelope, _SOAP_CONTENT_TYPE)
        return request.with_header(_SOAP_ACTION_HEADER, action) if action is not None else request

    def with_form(self, values: Mapping[str, str] | Sequence[tuple[str, str]]) -> "HttpRequest":
        encoded = urlencode(_text_pairs(values, field_name="form values")).encode(_UTF_8)
        return self.with_content(encoded, media_type=_FORM_CONTENT_TYPE)

    def with_multipart(self, parts: Sequence[MultipartPart], *, boundary: str | None = None) -> "HttpRequest":
        boundary = boundary or token_hex(DEFAULT_MULTIPART_BOUNDARY_BYTES)
        if not boundary or any(character.isspace() for character in boundary):
            raise ValueError("multipart boundary must be non-empty and contain no whitespace")
        if not parts:
            raise ValueError("multipart request requires at least one part")
        if any(not isinstance(part, MultipartPart) for part in parts):
            raise TypeError("multipart parts must be MultipartPart values")
        body = _encode_multipart(tuple(parts), boundary)
        return self.with_content(body, media_type=f"{MediaType.MULTIPART_FORM}; boundary={boundary}")

    def _with_text_content(self, value: str, media_type: str) -> "HttpRequest":
        if not isinstance(value, str):
            raise TypeError("text content must be a string")
        return self.with_content(value.encode(_UTF_8), media_type=media_type)

    def _replace(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None | object = _UNSET,
        timeout: HttpTimeout | None | object = _UNSET,
        query: tuple[tuple[str, str], ...] | None = None,
    ) -> "HttpRequest":
        return HttpRequest(
            self.method,
            self.url,
            self.headers if headers is None else headers,
            self.content if content is _UNSET else content,  # type: ignore[arg-type]
            self.timeout if timeout is _UNSET else timeout,  # type: ignore[arg-type]
            self.query if query is None else query,
        )


def _encode_multipart(parts: tuple[MultipartPart, ...], boundary: str) -> bytes:
    delimiter = f"--{boundary}".encode(_UTF_8)
    chunks: list[bytes] = []
    for part in parts:
        disposition = f'Content-Disposition: form-data; name="{part.name}"'
        if part.filename is not None:
            disposition = f'{disposition}; filename="{part.filename}"'
        chunks.extend((delimiter, b"\r\n", disposition.encode(_UTF_8), b"\r\n"))
        if part.media_type is not None:
            chunks.extend((f"Content-Type: {part.media_type}".encode(_UTF_8), b"\r\n"))
        chunks.extend((b"\r\n", part.content, b"\r\n"))
    chunks.extend((delimiter, b"--\r\n"))
    return b"".join(chunks)


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A bounded, fully-read response whose lifecycle is already complete."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes
    method: str
    url: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _freeze_headers(self.headers))

    @property
    def is_success(self) -> bool:
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    def require_success(self) -> "HttpResponse":
        if not self.is_success:
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    def text(self, encoding: str = "utf-8") -> str:
        try:
            return self.body.decode(encoding)
        except UnicodeDecodeError as error:
            raise HttpDecodeError("response body is not valid text", method=self.method, url=self.url) from error

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HttpDecodeError("response body is not valid JSON", method=self.method, url=self.url) from error


class HttpStreamResponse:
    """A synchronous response stream with no HTTPX value in its public contract."""

    def __init__(
        self,
        *,
        status_code: int,
        headers: Mapping[str, str],
        method: str,
        url: str,
        iter_bytes: Callable[[], Iterator[bytes]],
        close: Callable[[], None],
    ) -> None:
        self.status_code = status_code
        self.headers = _freeze_headers(headers)
        self.method = method
        self.url = url
        self._iter_bytes = iter_bytes
        self._close = close
        self._closed = False

    @property
    def is_success(self) -> bool:
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    def require_success(self) -> "HttpStreamResponse":
        if not self.is_success:
            self.close()
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    def iter_bytes(self) -> Iterator[bytes]:
        self._require_open()
        try:
            yield from self._iter_bytes()
        finally:
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._close()
            self._closed = True

    def __enter__(self) -> "HttpStreamResponse":
        self._require_open()
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise HttpStreamClosedError("HTTP response stream is closed", method=self.method, url=self.url)


class AsyncHttpStreamResponse:
    """An asynchronous response stream with no HTTPX value in its public contract."""

    def __init__(
        self,
        *,
        status_code: int,
        headers: Mapping[str, str],
        method: str,
        url: str,
        iter_bytes: Callable[[], AsyncIterator[bytes]],
        close: Callable[[], object],
    ) -> None:
        self.status_code = status_code
        self.headers = _freeze_headers(headers)
        self.method = method
        self.url = url
        self._iter_bytes = iter_bytes
        self._close = close
        self._closed = False

    @property
    def is_success(self) -> bool:
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    async def require_success(self) -> "AsyncHttpStreamResponse":
        if not self.is_success:
            await self.aclose()
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        self._require_open()
        try:
            async for chunk in self._iter_bytes():
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            result = self._close()
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]
            self._closed = True

    async def __aenter__(self) -> "AsyncHttpStreamResponse":
        self._require_open()
        return self

    async def __aexit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        await self.aclose()

    def _require_open(self) -> None:
        if self._closed:
            raise HttpStreamClosedError("HTTP response stream is closed", method=self.method, url=self.url)
