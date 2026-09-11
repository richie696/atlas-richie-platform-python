"""版本化、无状态 MCP 2026-07-28 线协议原语。

中文
----
定义 MCP 2026-07-28 dialect 的核心常量、数据结构与编 / 解码入口：

- 常量：`JSON_RPC_VERSION` (`2.0`) / `MODERN_PROTOCOL_VERSION` (`2026-07-28`)
  / 三个 `_meta` key。
- `Implementation`：可序列化的 MCP 端点身份（name / version / 可选 title /
  description）。
- `Request`：已解析的请求，归一化到业务代码（**不暴露原始 envelope**）。
- `McpDialect` Protocol + `Mcp20260728Dialect`：dialect 策略边界，
  解析 / 编码 入口。
- `parse_request` / `success` / `failure`：默认方言的兼容外观。

校验要求：JSON-RPC `2.0` envelope、`method` 非空字符串、`id` 缺失视为
notification、`_meta` 必须包含 `protocolVersion` / `clientCapabilities`、
`MCP-Protocol-Version` header 与 `_meta.protocolVersion` 一致。

English
--------
Versioned, stateless MCP 2026-07-28 wire protocol primitives.

Defines the core constants, data structures, and encode / decode
entry points for the MCP 2026-07-28 dialect.

- Constants: `JSON_RPC_VERSION` (`2.0`), `MODERN_PROTOCOL_VERSION`
  (`2026-07-28`), three `_meta` keys.
- `Implementation`: serialisable MCP endpoint identity (name / version
  / optional title / description).
- `Request`: parsed request, normalised for business code (**never
  exposes the raw envelope**).
- `McpDialect` Protocol + `Mcp20260728Dialect`: dialect strategy
  boundary — parse / encode entry points.
- `parse_request` / `success` / `failure`: compatibility facades over
  the default dialect.

Validation requirements: JSON-RPC `2.0` envelope, non-empty `method`
string, missing `id` is treated as a notification, `_meta` must
contain `protocolVersion` and `clientCapabilities`, the
`MCP-Protocol-Version` header must match `_meta.protocolVersion`.

Mirrors `cn.richie696.component.mcp.protocol.dialect.McpProtocolDialect`
+ `Mcp20260728Dialect` + `McpMetaKeys` (Java).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import McpError, ProtocolError

JSON_RPC_VERSION = "2.0"
MODERN_PROTOCOL_VERSION = "2026-07-28"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"


@dataclass(frozen=True, slots=True)
class Implementation:
    """中文
    ----
    MCP 端点对外广播的稳定、可序列化身份（`name` / `version` 必填）。

    English
    --------
    The stable, serializable identity advertised by an MCP endpoint.
    `name` and `version` are required.
    """

    name: str
    version: str
    title: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("implementation name and version are required")

    def as_json(self) -> dict[str, str]:
        """中文
        ----
        渲染为 MCP `implementation` 协议 JSON 形态（仅公开字段）。

        English
        --------
        Render to the JSON shape exposed by the MCP `implementation`
        object (public fields only).
        """
        result = {"name": self.name, "version": self.version}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class Request:
    """中文
    ----
    归一化的 MCP 请求；业务代码**永不**接触原始 JSON-RPC envelope。

    - `request_id`：通知时为 `None`。
    - `is_notification`：`True` 表示无 `id` 字段，调用方**不**应回响应。
    - `meta`：从 `params._meta` 提取的元数据；notification 时为空 dict。

    English
    --------
    A normalized MCP request; business code never receives the raw
    envelope.

    - `request_id`: `None` for notifications.
    - `is_notification`: `True` means the payload had no `id`; the
      caller must not send a response.
    - `meta`: the metadata extracted from `params._meta`; empty dict
      for notifications.
    """

    request_id: str | int | None
    method: str
    params: Mapping[str, Any]
    meta: Mapping[str, Any]
    is_notification: bool = False


class McpDialect(Protocol):
    """中文
    ----
    未来 MCP 协议代际的策略边界；当前实现是 `Mcp20260728Dialect`。

    English
    --------
    Strategy boundary for future MCP protocol generations. The
    current implementation is `Mcp20260728Dialect`.
    """

    @property
    def version(self) -> str: ...

    def parse_request(self, payload: object, *, transport_version: str | None = None) -> Request: ...

    def encode_result(self, result: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Mcp20260728Dialect:
    """中文
    ----
    2026-07-28 无状态方言：会话元数据通过 `params._meta` 透传，取代
    initialize / session 握手。

    English
    --------
    The stateless dialect: request metadata replaces initialize /
    session state.
    """

    version: str = MODERN_PROTOCOL_VERSION

    def parse_request(self, payload: object, *, transport_version: str | None = None) -> Request:
        """中文
        ----
        把一个原始 JSON 值解析为 `Request`；所有错误以 `ProtocolError` 抛出。

        Args:
            payload: 已解码的 JSON-RPC 请求对象。
            transport_version: 可选的 `MCP-Protocol-Version` header 值；存在时
                必须与 `params._meta.protocolVersion` 一致。

        Returns:
            归一化的 `Request`。

        Raises:
            ProtocolError: JSON-RPC 格式、`method` 缺失、`id` 类型、
                `_meta` 缺失或不完整、版本不一致等场景。

        English
        --------
        Parse one raw JSON value into a `Request`; all failures are
        raised as `ProtocolError`.

        Args:
            payload: the decoded JSON-RPC request object.
            transport_version: optional `MCP-Protocol-Version` header
                value; when present, must match
                `params._meta.protocolVersion`.

        Returns:
            the normalised `Request`.

        Raises:
            ProtocolError: bad JSON-RPC envelope, missing / empty
                `method`, wrong `id` type, missing or incomplete
                `_meta`, version mismatch.
        """
        if not isinstance(payload, Mapping):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "object_required"})
        if payload.get("jsonrpc") != JSON_RPC_VERSION:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "jsonrpc_must_be_2.0"})
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "method_required"})
        is_notification = "id" not in payload
        raw_id = payload.get("id")
        if not is_notification and (raw_id is None or isinstance(raw_id, bool) or not isinstance(raw_id, str | int)):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "id_must_be_string_or_integer"})
        params = payload.get("params", {})
        if not isinstance(params, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "params_must_be_object"})
        if method.startswith("notifications/"):
            return Request(raw_id, method, params, {}, is_notification=True)
        meta = params.get("_meta")
        if not isinstance(meta, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "modern_meta_required"})
        request_version = meta.get(PROTOCOL_VERSION_META_KEY)
        if request_version != self.version:
            raise ProtocolError(-32022, "Unsupported protocol version", {"supported": [self.version], "requested": request_version})
        if transport_version is not None and request_version != transport_version:
            raise ProtocolError(-32020, "MCP-Protocol-Version header does not match request metadata", {"metadata": request_version, "header": transport_version})
        if not isinstance(meta.get(CLIENT_CAPABILITIES_META_KEY), Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "client_capabilities_required"})
        client_info = meta.get(CLIENT_INFO_META_KEY)
        if client_info is not None and not isinstance(client_info, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "client_info_must_be_object"})
        return Request(raw_id, method, params, meta, is_notification=is_notification)

    def encode_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        """中文
        ----
        编码结果对象，校验 `resultType` ∈ {`complete`, `input_required`}。

        Args:
            result: 业务方构造的结果 dict。

        Returns:
            防御性拷贝后的 dict（防止后续修改污染已发响应）。

        Raises:
            ProtocolError: `resultType` 缺失或非法。

        English
        --------
        Encode a result object, validating that `resultType` is
        `complete` or `input_required`.

        Args:
            result: the caller-built result dict.

        Returns:
            a defensive copy of the dict (so later mutations cannot
            affect an already-sent response).

        Raises:
            ProtocolError: missing or invalid `resultType`.
        """
        encoded = dict(result)
        if encoded.get("resultType") not in {"complete", "input_required"}:
            raise ProtocolError(-32603, "Internal error", {"reason": "result_type_required"})
        return encoded


DEFAULT_DIALECT = Mcp20260728Dialect()


def parse_request(payload: object, *, transport_version: str | None = None) -> Request:
    """中文
    ----
    默认当前方言的解析兼容外观。

    Args:
        payload: 已解码的 JSON-RPC 请求对象。
        transport_version: 可选的 `MCP-Protocol-Version` header 值。

    Returns:
        归一化的 `Request`。

    English
    --------
    Compatibility facade for the default current dialect.

    Args:
        payload: the decoded JSON-RPC request object.
        transport_version: optional `MCP-Protocol-Version` header
            value.

    Returns:
        the normalised `Request`.
    """

    return DEFAULT_DIALECT.parse_request(payload, transport_version=transport_version)


def success(request_id: str | int, result: Mapping[str, Any], *, dialect: McpDialect = DEFAULT_DIALECT) -> dict[str, Any]:
    """中文
    ----
    构造 JSON-RPC 成功 envelope；先经 dialect 层 result 校验。

    Args:
        request_id: 透传自请求的 `id`。
        result: 业务结果。
        dialect: 用于编码 `result` 的方言，默认 `DEFAULT_DIALECT`。

    Returns:
        `{"jsonrpc": "2.0", "id": ..., "result": ...}`。

    English
    --------
    Create a JSON-RPC success envelope after dialect-level result
    validation.

    Args:
        request_id: the `id` echoed from the request.
        result: the business result.
        dialect: dialect used to encode `result`; default
            `DEFAULT_DIALECT`.

    Returns:
        `{"jsonrpc": "2.0", "id": ..., "result": ...}`.
    """

    return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": dialect.encode_result(result)}


def failure(request_id: str | int | None, error: McpError) -> dict[str, Any]:
    """中文
    ----
    构造 JSON-RPC 错误 envelope；不暴露实现细节（仅 code / message / data）。

    Args:
        request_id: 透传自请求的 `id`（解析失败时可能为 `None`）。
        error: 已分类的 `McpError` 派生实例。

    Returns:
        `{"jsonrpc": "2.0", "id": ..., "error": ...}`。

    English
    --------
    Create a JSON-RPC error envelope without exposing implementation
    details.

    Args:
        request_id: the `id` echoed from the request (may be `None`
            on parse failure).
        error: a categorised `McpError` subclass instance.

    Returns:
        `{"jsonrpc": "2.0", "id": ..., "error": ...}`.
    """

    return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "error": error.as_json()}
