"""按可移植行为分类的 HTTP 失败（不依赖 HTTPX 自身类型）。
----
本模块定义 `atlas_richie.http` 抛出的所有受控异常。分类原则是
**可移植行为**（调用方真正需要处理的语义）而不是 HTTPX 内部
类型：

- `HttpError`：根异常；所有受控失败都派生自它
- `HttpClientClosedError` / `HttpStreamClosedError`：生命周期结束
  后仍被使用
- `HttpTransportError`：未分类的网络/传输失败基类
- `HttpConnectError` / `HttpTimeoutError` / `HttpProtocolError`：
  按连接/超时/协议违例进一步细分的传输错误
- `HttpResponseLimitError`：流式读取时超过 `max_response_bytes`
- `HttpDecodeError`：响应体无法解码为请求的表示（文本/JSON）
- `HttpStatusError`：调用方显式要求成功状态但服务端返回其他状态

`safe_url` 工具函数负责在把 URL 写入异常或审计事件前剥离
query 和 fragment，避免敏感参数泄漏到日志/指标里。

English
--------
HTTP failures classified by portable behaviour rather than by
HTTPX's own type hierarchy.

- `HttpError`: root for all controlled failures
- `HttpClientClosedError` / `HttpStreamClosedError`: used after
  explicit lifecycle ended
- `HttpTransportError`: base for unclassified network/transport
  failures
- `HttpConnectError` / `HttpTimeoutError` / `HttpProtocolError`:
  transport errors split by failure mode
- `HttpResponseLimitError`: streaming read exceeded
  `max_response_bytes`
- `HttpDecodeError`: body cannot be decoded into the requested
  representation
- `HttpStatusError`: caller required success but server returned
  another status

`safe_url` strips query and fragment before a URL is retained in
an error or audit event, so secrets in query strings do not leak
to logs / metrics.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def safe_url(url: str) -> str:
    """在把 URL 写入异常或审计事件前剥离 query 与 fragment。

    English
    --------
    Remove query and fragment before a URL is retained in an error
    or audit event.
    """

    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class HttpError(Exception):
    """受控出站 HTTP 失败的基类。

    English
    --------
    Base class for controlled outbound HTTP failures.
    """

    def __init__(self, message: str, *, method: str | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.method = method
        self.url = safe_url(url) if url is not None else None


class HttpClientClosedError(HttpError):
    """客户端在显式生命周期结束后仍被使用。

    English
    --------
    A client was used after its explicit lifecycle ended.
    """


class HttpStreamClosedError(HttpError):
    """响应流在显式生命周期结束后仍被使用。

    English
    --------
    A response stream was used after its explicit lifecycle ended.
    """


class HttpTransportError(HttpError):
    """未分类的网络或传输失败。

    English
    --------
    An unclassified network or transport failure.
    """


class HttpConnectError(HttpTransportError):
    """无法建立连接。

    English
    --------
    A connection could not be established.
    """


class HttpTimeoutError(HttpTransportError):
    """connect / read / write / pool 超时。

    English
    --------
    A connect, read, write, or pool timeout elapsed.
    """


class HttpProtocolError(HttpTransportError):
    """远端违反 HTTP 协议。

    English
    --------
    The remote endpoint violated the HTTP protocol.
    """


class HttpResponseLimitError(HttpError):
    """流式读取时超过 `max_response_bytes` 限制。

    English
    --------
    The configured response-body limit was exceeded while streaming.
    """

    def __init__(self, limit: int, *, method: str, url: str) -> None:
        super().__init__(f"response body exceeds {limit} bytes", method=method, url=url)
        self.limit = limit


class HttpDecodeError(HttpError):
    """响应体无法解码为请求的表示。

    English
    --------
    A response body cannot be decoded into the requested
    representation.
    """


class HttpStatusError(HttpError):
    """调用方显式要求成功状态但收到了其他状态码。

    English
    --------
    A caller explicitly required a successful HTTP status but
    received another one.
    """

    def __init__(self, status_code: int, *, method: str, url: str) -> None:
        super().__init__(f"unexpected HTTP status: {status_code}", method=method, url=url)
        self.status_code = status_code
