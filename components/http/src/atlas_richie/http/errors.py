"""HTTP failures classified by portable behavior instead of HTTPX types."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def safe_url(url: str) -> str:
    """Remove query and fragment before a URL is retained in an error or audit event."""

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class HttpError(Exception):
    """Base class for controlled outbound HTTP failures."""

    def __init__(self, message: str, *, method: str | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.method = method
        self.url = safe_url(url) if url is not None else None


class HttpClientClosedError(HttpError):
    """A client was used after its explicit lifecycle ended."""


class HttpStreamClosedError(HttpError):
    """A response stream was used after its explicit lifecycle ended."""


class HttpTransportError(HttpError):
    """An unclassified network or transport failure."""


class HttpConnectError(HttpTransportError):
    """A connection could not be established."""


class HttpTimeoutError(HttpTransportError):
    """A connect, read, write, or pool timeout elapsed."""


class HttpProtocolError(HttpTransportError):
    """The remote endpoint violated the HTTP protocol."""


class HttpResponseLimitError(HttpError):
    """The configured response-body limit was exceeded while streaming."""

    def __init__(self, limit: int, *, method: str, url: str) -> None:
        super().__init__(f"response body exceeds {limit} bytes", method=method, url=url)
        self.limit = limit


class HttpDecodeError(HttpError):
    """A response body cannot be decoded into the requested representation."""


class HttpStatusError(HttpError):
    """A caller explicitly required a successful HTTP status but received another one."""

    def __init__(self, status_code: int, *, method: str, url: str) -> None:
        super().__init__(f"unexpected HTTP status: {status_code}", method=method, url=url)
        self.status_code = status_code
