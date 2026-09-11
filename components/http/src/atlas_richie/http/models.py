"""可移植的 HTTP 请求、响应与客户端选项值。
----
本模块定义 `atlas_richie.http` 在传输层之上流动的所有值类型，
**不**包含任何 HTTPX 类型，使得上层业务能脱离具体 transport 实现
来调用。

核心值：

- `HttpMethod` / `MediaType`：枚举形式的 method 与 media type，
  配合 `HttpRequest.json` / `with_xml` / `with_soap` /
  `with_form` / `with_multipart` 提供 first-class 构造语义。
- `MultipartPart`：不可变的 multipart 部件（`name` / `content` /
  可选 `filename` 与 `media_type`），流式 file-like 句柄仍由应用层
  持有，本类只接收已就绪的 `bytes`。
- `HttpTimeout`：connect / read / write / pool 四档独立超时预算。
- `HttpClientOptions`：客户端级限制 + 安全默认值
  （`follow_redirects=False`、`max_response_bytes` 默认 4 MiB、
  `headers` 在构造时冻结为只读映射）。
- `HttpRequest`：不可变出站请求，所有变更通过 `with_*` 链式
  方法返回新实例。`__post_init__` 在构造期校验 method / url /
  content 类型并把 `headers` / `query` 冻结。
- `HttpResponse`：已完整读取的响应，`is_success` / `require_success`
  / `text` / `json` 是其核心消费面；解码失败抛 `HttpDecodeError`。
- `HttpStreamResponse` / `AsyncHttpStreamResponse`：流式响应，
  公共契约不出现 HTTPX 类型；通过 `iter_bytes` / `aiter_bytes`
  消费，结束 / 出错 / 上下文管理器退出时自动 `close` / `aclose`。

辅助函数：`header_value` / `with_header`（case-insensitive 头
匹配）、`_freeze_headers`（映射冻结）、`_text_pairs`（规范化
key-value 对）。

English
--------
Portable HTTP request, response, and client-option values.

This module owns every value type that flows above the transport
layer in `atlas_richie.http`. No HTTPX value is part of the
public surface, so the caller is shielded from the underlying
transport.

Core values:

- `HttpMethod` / `MediaType`: enums used as first-class
  request-construction arguments
  (`HttpRequest.json` / `with_xml` / `with_soap` / `with_form` /
  `with_multipart`).
- `MultipartPart`: immutable multipart part (`name` / `content`
  + optional `filename` / `media_type`). File-like streams remain
  application-owned; this class only accepts already-materialised
  `bytes`.
- `HttpTimeout`: independent connect / read / write / pool budgets.
- `HttpClientOptions`: client-wide limits + secure defaults
  (`follow_redirects=False`, `max_response_bytes` default 4 MiB,
  `headers` frozen at construction).
- `HttpRequest`: immutable outbound request. Every change goes
  through a `with_*` chain that returns a new instance.
  `__post_init__` validates method / url / content type and
  freezes `headers` / `query`.
- `HttpResponse`: bounded, fully-read response.
  `is_success` / `require_success` / `text` / `json` are the
  primary consumption surface. Decode failures raise
  `HttpDecodeError`.
- `HttpStreamResponse` / `AsyncHttpStreamResponse`: stream
  responses. The public contract carries no HTTPX value; consume
  via `iter_bytes` / `aiter_bytes`; auto-close on completion,
  failure, or context-manager exit.

Helpers: `header_value` / `with_header` (case-insensitive
header matching), `_freeze_headers` (mapping freeze),
`_text_pairs` (key-value pair normalisation).
"""

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
    """标准请求方法，提供具名构造入口。

    English
    --------
    Standard request methods offered as named request
    constructors.
    """

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class MediaType(StrEnum):
    """媒体类型，提供 first-class 请求构造语义。

    English
    --------
    Media types with first-class request construction
    semantics.
    """

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
    """按 HTTP 头大小写不敏感语义取值。

    English
    --------
    Return a header value with HTTP's case-insensitive name
    matching.
    """

    expected = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == expected), None)


def with_header(headers: Mapping[str, str], name: str, value: str) -> Mapping[str, str]:
    """返回新的不可变映射，替换已存在的同名（大小写不敏感）头。

    English
    --------
    Return a new immutable mapping, replacing an existing
    case-insensitive header.
    """

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
    """一个不可变的 multipart/form-data 部件；file-like 流仍由应用层持有。

    English
    --------
    One immutable multipart/form-data part; file-like streams
    stay application-owned.
    """

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
    """显式的、按操作拆分的超时预算（秒）。

    English
    --------
    Explicit per-operation timeout budget in seconds.
    """

    connect: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read: float = DEFAULT_READ_TIMEOUT_SECONDS
    write: float = DEFAULT_WRITE_TIMEOUT_SECONDS
    pool: float = DEFAULT_POOL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if any(value <= 0 for value in (self.connect, self.read, self.write, self.pool)):
            raise ValueError("all timeout values must be positive")


@dataclass(frozen=True, slots=True)
class HttpClientOptions:
    """组件自带的客户端级限制与安全默认值。

    English
    --------
    Client-wide limits and secure defaults owned by the
    component.
    """

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
    """不可变出站 HTTP 请求，公共契约不出现任何 transport 库类型。

    English
    --------
    An immutable outbound HTTP request with no transport-library
    types.
    """

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
        """构造一个 GET 请求。

        Args:
            url: 目标 URL
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例。

        English
        --------
        Build a GET request.
        """
        return cls(HttpMethod.GET, url, headers or {})

    @classmethod
    def post(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        """构造一个 POST 请求。

        Args:
            url: 目标 URL
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例。

        English
        --------
        Build a POST request.
        """
        return cls(HttpMethod.POST, url, headers or {})

    @classmethod
    def put(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        """构造一个 PUT 请求。

        Args:
            url: 目标 URL
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例。

        English
        --------
        Build a PUT request.
        """
        return cls(HttpMethod.PUT, url, headers or {})

    @classmethod
    def patch(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        """构造一个 PATCH 请求。

        Args:
            url: 目标 URL
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例。

        English
        --------
        Build a PATCH request.
        """
        return cls(HttpMethod.PATCH, url, headers or {})

    @classmethod
    def delete(cls, url: str, *, headers: Mapping[str, str] | None = None) -> "HttpRequest":
        """构造一个 DELETE 请求。

        Args:
            url: 目标 URL
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例。

        English
        --------
        Build a DELETE request.
        """
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
        """构造一个以 JSON 为 body 的请求。

        Args:
            method: HTTP method
            url: 目标 URL
            value: 任意 JSON 可序列化对象
            headers: 可选请求头

        Returns:
            对应的 `HttpRequest` 实例（已自动设置 `Content-Type`）。

        English
        --------
        Build a request with a JSON body (auto-sets Content-Type).
        """
        return cls(method, url, headers or {}).with_json(value)

    def with_header(self, name: str, value: str) -> "HttpRequest":
        """返回带替换/新增头的新请求实例。

        Args:
            name: 头名（大小写不敏感）
            value: 头值

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Return a new request with the given header set (replaces
        any existing case-insensitive match).
        """
        return self._replace(headers=with_header(self.headers, name, value))

    def with_headers(self, headers: Mapping[str, str]) -> "HttpRequest":
        """批量设置多个头；按字典序保留调用顺序。

        Args:
            headers: 头名到头值的映射

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Set multiple headers; insertion order follows the
        input mapping.
        """
        result = self
        for name, value in headers.items():
            result = result.with_header(name, value)
        return result

    def with_query_param(self, name: str, value: str) -> "HttpRequest":
        """追加单个 query 参数。

        Args:
            name: 参数名
            value: 参数值

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Append a single query parameter.
        """
        return self._replace(query=(*self.query, *_text_pairs(((name, value),), field_name="query parameters")))

    def with_query_params(self, values: Mapping[str, str] | Sequence[tuple[str, str]]) -> "HttpRequest":
        """追加多个 query 参数。

        Args:
            values: query 参数映射或键值对序列

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Append multiple query parameters.
        """
        return self._replace(query=(*self.query, *_text_pairs(values, field_name="query parameters")))

    def with_timeout(self, timeout: HttpTimeout) -> "HttpRequest":
        """为单次请求覆盖超时。

        Args:
            timeout: 新的 `HttpTimeout`

        Returns:
            新的 `HttpRequest` 实例。

        Raises:
            TypeError: 参数不是 `HttpTimeout` 时。

        English
        --------
        Override the per-request timeout budget.
        """
        if not isinstance(timeout, HttpTimeout):
            raise TypeError("timeout must be an HttpTimeout")
        return self._replace(timeout=timeout)

    def with_content(self, content: bytes | None, *, media_type: str | None = None) -> "HttpRequest":
        """设置请求体并按需设置 `Content-Type`。

        Args:
            content: 字节体；`None` 表示无 body
            media_type: 显式 `Content-Type`；仅在未设置时生效

        Returns:
            新的 `HttpRequest` 实例。

        Raises:
            ValueError: `media_type` 非合法字符串时。

        English
        --------
        Set the request body, optionally setting Content-Type
        when it isn't already set.
        """
        if media_type is not None and (not isinstance(media_type, str) or not media_type.strip()):
            raise ValueError("media_type must be a non-blank string when present")
        headers = _with_content_type(self.headers, media_type) if media_type else self.headers
        return self._replace(headers=headers, content=content)

    def with_json(self, value: Any) -> "HttpRequest":
        """把 `value` 编码为 JSON，并自动设置 `Content-Type`。

        Args:
            value: 任意 JSON 可序列化对象

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Serialise `value` to JSON and set Content-Type to
        `application/json; charset=utf-8`.
        """
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(_UTF_8)
        return self.with_content(content, media_type=_JSON_CONTENT_TYPE)

    def with_xml(self, value: str) -> "HttpRequest":
        """把字符串作为 XML body，并设置 `Content-Type`。

        Args:
            value: XML 文本

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Use `value` as an XML body and set the matching
        Content-Type.
        """
        return self._with_text_content(value, _XML_CONTENT_TYPE)

    def with_soap(self, envelope: str, *, action: str | None = None) -> "HttpRequest":
        """构造一个 SOAP 1.2 请求。

        Args:
            envelope: SOAP 信封字符串
            action: 可选 `SOAPAction` 头

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        Build a SOAP 1.2 request, optionally setting the
        `SOAPAction` header.
        """
        request = self._with_text_content(envelope, _SOAP_CONTENT_TYPE)
        return request.with_header(_SOAP_ACTION_HEADER, action) if action is not None else request

    def with_form(self, values: Mapping[str, str] | Sequence[tuple[str, str]]) -> "HttpRequest":
        """把键值对编码为 `application/x-www-form-urlencoded` body。

        Args:
            values: 表单键值对

        Returns:
            新的 `HttpRequest` 实例。

        English
        --------
        URL-encode key/value pairs as
        `application/x-www-form-urlencoded` body.
        """
        encoded = urlencode(_text_pairs(values, field_name="form values")).encode(_UTF_8)
        return self.with_content(encoded, media_type=_FORM_CONTENT_TYPE)

    def with_multipart(self, parts: Sequence[MultipartPart], *, boundary: str | None = None) -> "HttpRequest":
        """用 `parts` 构造 `multipart/form-data` body。

        Args:
            parts: 不可变 `MultipartPart` 序列
            boundary: 自定义 boundary；不传则用 `token_hex` 生成

        Returns:
            新的 `HttpRequest` 实例（`Content-Type` 含 boundary）。

        Raises:
            ValueError: `boundary` 含空白 / `parts` 为空 时。
            TypeError: `parts` 中存在非 `MultipartPart` 时。

        English
        --------
        Build a `multipart/form-data` body from `parts`.
        """
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
    """一个有界、已完整读取、生命周期已结束的响应。

    English
    --------
    A bounded, fully-read response whose lifecycle is already
    complete.
    """

    status_code: int
    headers: Mapping[str, str]
    body: bytes
    method: str
    url: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _freeze_headers(self.headers))

    @property
    def is_success(self) -> bool:
        """200 ≤ status < 300 即为成功。

        English
        --------
        `True` when `200 <= status_code < 300`.
        """
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    def require_success(self) -> "HttpResponse":
        """非成功状态抛 `HttpStatusError`；否则返回自身。

        Raises:
            HttpStatusError: 状态码不在 `[200, 300)` 区间。

        English
        --------
        Raise `HttpStatusError` unless the status code is
        successful; otherwise return self.
        """
        if not self.is_success:
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    def text(self, encoding: str = "utf-8") -> str:
        """把 body 解码为字符串。

        Args:
            encoding: 解码编码，默认 `utf-8`

        Returns:
            解码后的字符串。

        Raises:
            HttpDecodeError: body 不是合法 `encoding` 文本时。

        English
        --------
        Decode the body to text. Raises `HttpDecodeError` on
        decode failure.
        """
        try:
            return self.body.decode(encoding)
        except UnicodeDecodeError as error:
            raise HttpDecodeError("response body is not valid text", method=self.method, url=self.url) from error

    def json(self) -> Any:
        """把 body 解析为 JSON。

        Returns:
            解析结果。

        Raises:
            HttpDecodeError: body 不是合法 JSON / utf-8 时。

        English
        --------
        Parse the body as JSON. Raises `HttpDecodeError` on
        parse failure.
        """
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HttpDecodeError("response body is not valid JSON", method=self.method, url=self.url) from error


class HttpStreamResponse:
    """同步响应流，公共契约不出现任何 HTTPX 值。

    English
    --------
    A synchronous response stream with no HTTPX value in its
    public contract.
    """

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
        """200 ≤ status < 300 即为成功。

        English
        --------
        `True` when `200 <= status_code < 300`.
        """
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    def require_success(self) -> "HttpStreamResponse":
        """非成功状态：先 `close` 再抛 `HttpStatusError`；否则返回自身。

        Raises:
            HttpStatusError: 状态码不在 `[200, 300)` 区间。

        English
        --------
        Close the stream and raise `HttpStatusError` unless the
        status code is successful; otherwise return self.
        """
        if not self.is_success:
            self.close()
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    def iter_bytes(self) -> Iterator[bytes]:
        """产出字节块；无论是否异常退出，都会 `close` 流。

        English
        --------
        Yield body chunks; the stream is closed when the
        iterator is exhausted, fails, or the generator is
        garbage-collected.
        """
        self._require_open()
        try:
            yield from self._iter_bytes()
        finally:
            self.close()

    def close(self) -> None:
        """关闭底层响应流；重复调用安全。

        English
        --------
        Close the underlying response stream; repeated calls
        are safe.
        """

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
    """异步响应流，公共契约不出现任何 HTTPX 值。

    English
    --------
    An asynchronous response stream with no HTTPX value in its
    public contract.
    """

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
        """200 ≤ status < 300 即为成功。

        English
        --------
        `True` when `200 <= status_code < 300`.
        """
        return SUCCESS_STATUS_MIN <= self.status_code < SUCCESS_STATUS_EXCLUSIVE_MAX

    async def require_success(self) -> "AsyncHttpStreamResponse":
        """非成功状态：先 `aclose` 再抛 `HttpStatusError`；否则返回自身。

        Raises:
            HttpStatusError: 状态码不在 `[200, 300)` 区间。

        English
        --------
        Close the stream and raise `HttpStatusError` unless the
        status code is successful; otherwise return self.
        """
        if not self.is_success:
            await self.aclose()
            raise HttpStatusError(self.status_code, method=self.method, url=self.url)
        return self

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        """异步产出字节块；无论是否异常退出，都会 `aclose` 流。

        English
        --------
        Yield body chunks; the stream is closed when the
        iterator is exhausted, fails, or the generator is
        garbage-collected.
        """
        self._require_open()
        try:
            async for chunk in self._iter_bytes():
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """关闭底层异步响应流；重复调用安全。

        English
        --------
        Close the underlying async response stream; repeated
        calls are safe.
        """

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
