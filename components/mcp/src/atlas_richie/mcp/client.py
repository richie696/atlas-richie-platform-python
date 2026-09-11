"""MCP 2026-07-28 无状态协议的传输无关客户端外观。

中文
----
`McpClient` 是协议级别的客户端外观；**网络 / 进程 I/O 由调用方注入的
`Exchange` 协程负责**（HTTP、stdio、Streamable HTTP、SSE 等）。

设计要点：

- **传输解耦**：`McpClient` 只依赖 `Exchange = Callable[[Mapping],
  Awaitable[Mapping | None]]`；`McpClientDialect` 协议允许不同协议代际
  共存。
- **缓存**：仅对
  `server/discover` / `tools/list` / `resources/list` /
  `resources/templates/list` / `resources/read` / `prompts/list`
  这 6 个可缓存方法生效；缓存键 = `(version, identity.name, method,
  partition, serialized_params)`。
- **`cacheScope` 协议感知**：仅当远端响应携带 `cacheScope ∈ {public,
  private}` 且 `ttlMs` 为正整数时才缓存；`private` 缓存要求
  `cache_partition` 已注入。
- **`input_required` 永不缓存**。
- **游标分页**：`iter_*` 协程基于 `nextCursor` 自动翻页；重复 cursor 抛
  `McpError` 防环。
- **通知**：`server.handle` 返回 `None` 的场景被映射为"无响应"。

English
--------
Transport-neutral MCP client facade for the stateless 2026-07-28
protocol.

`McpClient` is the protocol-level client facade; **all network /
process I/O is performed by the caller-injected `Exchange` coroutine**
(HTTP, stdio, Streamable HTTP, SSE, …).

Design points:

- **Transport decoupled**: `McpClient` only depends on
  `Exchange = Callable[[Mapping], Awaitable[Mapping | None]]`;
  `McpClientDialect` lets different protocol generations coexist.
- **Cache**: only six cacheable methods — `server/discover`,
  `tools/list`, `resources/list`, `resources/templates/list`,
  `resources/read`, `prompts/list`. Cache key =
  `(version, identity.name, method, partition, serialized_params)`.
- **`cacheScope`-aware**: only cache when the response carries
  `cacheScope ∈ {public, private}` and `ttlMs` is a positive
  integer; `private` requires a `cache_partition`.
- **`input_required` is never cached**.
- **Cursor pagination**: `iter_*` coroutines walk `nextCursor`
  automatically; a repeated cursor raises `McpError` to break cycles.
- **Notifications**: `server.handle` returning `None` is mapped to
  "no response".

Mirrors `cn.richie696.component.mcp.api.McpClientRequest` +
`McpOperations` + `McpDynamicOperations` (Java — same shape, narrower
Python surface).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .cache import McpResponseCache
from .errors import McpError
from .protocol import CLIENT_CAPABILITIES_META_KEY, CLIENT_INFO_META_KEY, JSON_RPC_VERSION, MODERN_PROTOCOL_VERSION, PROTOCOL_VERSION_META_KEY, Implementation

Exchange = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any] | None]]
_CACHEABLE_METHODS = frozenset({
    "server/discover",
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "resources/read",
    "prompts/list",
})
_PRIVATE_CACHE_SCOPE = "private"
_PUBLIC_CACHE_SCOPE = "public"


class McpClientDialect(Protocol):
    """中文
    ----
    客户端侧方言协议；将"线缆差异"（metadata 注入位置、id 类型、缓存字段
    等）封装在 `dialect` 对象里，**不污染公共 API**。

    English
    --------
    Owns client-side wire differences without leaking them into
    public operations.
    """

    @property
    def version(self) -> str: ...

    def encode_request(
        self,
        *,
        request_id: int,
        method: str,
        params: Mapping[str, Any],
        identity: Implementation,
        capabilities: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    def decode_result(self, response: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ModernMcpClientDialect:
    """中文
    ----
    当前无状态 MCP 请求 / 结果映射的方言实现。

    English
    --------
    Current stateless MCP request and result mapping.
    """

    version: str = MODERN_PROTOCOL_VERSION

    def encode_request(
        self,
        *,
        request_id: int,
        method: str,
        params: Mapping[str, Any],
        identity: Implementation,
        capabilities: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """中文
        ----
        编码一个 JSON-RPC 请求；在 `params._meta` 注入 `protocolVersion` /
        `clientCapabilities` / `clientInfo`。

        Args:
            request_id: 单调递增请求 ID。
            method: 远端方法名。
            params: 业务参数。
            identity: 客户端身份。
            capabilities: 客户端能力声明。

        Returns:
            完整 JSON-RPC 请求对象。

        English
        --------
        Encode a JSON-RPC request; injects `protocolVersion` /
        `clientCapabilities` / `clientInfo` into `params._meta`.

        Args:
            request_id: monotonically increasing request id.
            method: remote method name.
            params: business parameters.
            identity: client identity.
            capabilities: client capability declaration.

        Returns:
            the full JSON-RPC request object.
        """
        return {
            "jsonrpc": JSON_RPC_VERSION,
            "id": request_id,
            "method": method,
            "params": {
                **dict(params),
                "_meta": {
                    PROTOCOL_VERSION_META_KEY: self.version,
                    CLIENT_CAPABILITIES_META_KEY: dict(capabilities),
                    CLIENT_INFO_META_KEY: identity.as_json(),
                },
            },
        }

    def decode_result(self, response: Mapping[str, Any]) -> Mapping[str, Any]:
        """中文
        ----
        从 JSON-RPC 响应中提取 result；要求 `resultType` ∈ {`complete`,
        `input_required`}。

        Args:
            response: JSON-RPC 响应对象。

        Returns:
            result 字段。

        Raises:
            McpError: 响应缺 result 或 `resultType` 非法。

        English
        --------
        Extract the result from a JSON-RPC response; requires
        `resultType` ∈ {`complete`, `input_required`}.

        Args:
            response: the JSON-RPC response object.

        Returns:
            the `result` field.

        Raises:
            McpError: response lacks a result, or `resultType` is
                invalid.
        """
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("resultType") not in {"complete", "input_required"}:
            raise McpError(-32603, "Invalid result response")
        return result


DEFAULT_CLIENT_DIALECT = ModernMcpClientDialect()


class McpClient:
    """中文
    ----
    协议级别客户端外观；传输适配器通过 `Exchange` 协程提供唯一的网络 /
    进程 I/O。

    Args:
        exchange: 注入的传输协程，签名 `(request) -> response | None`。
        identity: 客户端身份（默认 `atlas-richie-mcp-client/0.1.0`）。
        capabilities: 客户端能力声明。
        response_cache: 替换默认缓存的实例。
        cache_partition: 私有缓存命名空间（`cacheScope=private` 时必填）。
        dialect: 客户端方言（默认 `ModernMcpClientDialect`）。

    English
    --------
    Protocol facade; a transport adapter supplies the only network or
    process I/O.

    Args:
        exchange: injected transport coroutine, signature
            `(request) -> response | None`.
        identity: client identity (default
            `atlas-richie-mcp-client/0.1.0`).
        capabilities: client capability declaration.
        response_cache: override the default cache instance.
        cache_partition: private cache namespace (required when
            `cacheScope=private`).
        dialect: client dialect (default `ModernMcpClientDialect`).
    """

    def __init__(
        self,
        exchange: Exchange,
        *,
        identity: Implementation | None = None,
        capabilities: Mapping[str, Any] | None = None,
        response_cache: McpResponseCache | None = None,
        cache_partition: str | None = None,
        dialect: McpClientDialect = DEFAULT_CLIENT_DIALECT,
        request_id_offset: int = 0,
    ) -> None:
        self._exchange = exchange
        self._identity = identity or Implementation("atlas-richie-mcp-client", "0.1.0")
        self._capabilities = dict(capabilities or {})
        self._next_id = 0
        self._request_id_offset = request_id_offset
        self._response_cache = response_cache or McpResponseCache()
        self._cache_partition = cache_partition
        self._dialect = dialect

    async def discover(self) -> Mapping[str, Any]:
        """中文
        ----
        `negotiate()` 的语义别名（与 `server/discover` 同义）。

        English
        --------
        Semantic alias of `negotiate()`.
        """
        return await self.negotiate()

    async def negotiate(self, *, refresh: bool = False) -> Mapping[str, Any]:
        """中文
        ----
        发现远端的现代能力 profile；`refresh=True` 时绕过本地缓存。

        Args:
            refresh: 为 `True` 时强制走远端，忽略已有缓存。

        Returns:
            `server/discover` 响应体（`resultType=complete`）。

        English
        --------
        Discover the remote modern capability profile, using its
        declared cache policy.

        Args:
            refresh: when `True`, bypass the local cache and force a
                remote round-trip.

        Returns:
            the `server/discover` response body (`resultType=complete`).
        """
        return await self.request("server/discover", use_cache=not refresh)

    def invalidate_cache(self) -> None:
        """中文
        ----
        外部失效信号到达时清空本地 discovery / list / read 快照。

        English
        --------
        Forget local discovery / list / read snapshots after an
        external invalidation signal.
        """
        self._response_cache.invalidate()

    async def list_tools(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        """中文
        ----
        调用 `tools/list`；`cursor` 非空时透传给服务端作为续页游标。

        Args:
            cursor: 上次响应携带的 `nextCursor`。

        Returns:
            含 `tools` 列表 + 可选 `nextCursor` 的响应。

        English
        --------
        Call `tools/list`; pass `cursor` through when non-empty.

        Args:
            cursor: the `nextCursor` returned by the previous page
                (if any).

        Returns:
            response with a `tools` list and optional `nextCursor`.
        """
        return await self.request("tools/list", _cursor(cursor))

    async def iter_tools(self) -> AsyncIterator[Mapping[str, Any]]:
        """中文
        ----
        自动按 `nextCursor` 翻页迭代全部 tools；遇到重复 cursor 抛 `McpError`。

        English
        --------
        Walk every tool across `nextCursor` pages; raise `McpError` on
        repeated cursor.
        """
        async for item in self._paginate("tools/list", "tools"):
            yield item

    async def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None, *, request_state: str | None = None, input_responses: Mapping[str, Mapping[str, Any]] | None = None) -> Mapping[str, Any]:
        """中文
        ----
        调用 `tools/call`；支持多轮 `requestState` / `inputResponses` 透传。

        Args:
            name: tool 名。
            arguments: 业务参数。
            request_state: 多轮请求状态（来自 `InputRequired.requestState`）。
            input_responses: 多轮输入回答（key → 回答对象）。

        Returns:
            tool result 响应。

        English
        --------
        Call `tools/call`; pass through multi-round `requestState` /
        `inputResponses` when supplied.

        Args:
            name: tool name.
            arguments: business arguments.
            request_state: multi-round request state (from
                `InputRequired.requestState`).
            input_responses: multi-round input answers (key → answer
                object).

        Returns:
            tool result response.
        """
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        if request_state:
            params["requestState"] = request_state
        if input_responses:
            params["inputResponses"] = {key: dict(value) for key, value in input_responses.items()}
        return await self.request("tools/call", params)

    async def list_resources(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        """中文
        ----
        调用 `resources/list`；`cursor` 非空时透传。

        English
        --------
        Call `resources/list`; pass through `cursor` when non-empty.
        """
        return await self.request("resources/list", _cursor(cursor))

    async def iter_resources(self) -> AsyncIterator[Mapping[str, Any]]:
        """中文
        ----
        按 `nextCursor` 自动翻页迭代全部 resources。

        English
        --------
        Walk every resource across `nextCursor` pages.
        """
        async for item in self._paginate("resources/list", "resources"):
            yield item

    async def list_resource_templates(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        """中文
        ----
        调用 `resources/templates/list`；`cursor` 非空时透传。

        English
        --------
        Call `resources/templates/list`; pass through `cursor` when
        non-empty.
        """
        return await self.request("resources/templates/list", _cursor(cursor))

    async def iter_resource_templates(self) -> AsyncIterator[Mapping[str, Any]]:
        """中文
        ----
        按 `nextCursor` 自动翻页迭代全部 resource templates。

        English
        --------
        Walk every resource template across `nextCursor` pages.
        """
        async for item in self._paginate("resources/templates/list", "resourceTemplates"):
            yield item

    async def read_resource(self, uri: str) -> Mapping[str, Any]:
        """中文
        ----
        调用 `resources/read`；返回 `contents` 列表。

        Args:
            uri: 资源 URI。

        Returns:
            含 `contents` 列表的响应。

        English
        --------
        Call `resources/read`; return a `contents` list.

        Args:
            uri: resource URI.

        Returns:
            response with the `contents` list.
        """
        return await self.request("resources/read", {"uri": uri})

    async def list_prompts(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        """中文
        ----
        调用 `prompts/list`；`cursor` 非空时透传。

        English
        --------
        Call `prompts/list`; pass through `cursor` when non-empty.
        """
        return await self.request("prompts/list", _cursor(cursor))

    async def iter_prompts(self) -> AsyncIterator[Mapping[str, Any]]:
        """中文
        ----
        按 `nextCursor` 自动翻页迭代全部 prompts。

        English
        --------
        Walk every prompt across `nextCursor` pages.
        """
        async for item in self._paginate("prompts/list", "prompts"):
            yield item

    async def get_prompt(
        self,
        name: str,
        arguments: Mapping[str, str] | None = None,
        *,
        request_state: str | None = None,
        input_responses: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any]:
        """中文
        ----
        调用 `prompts/get`；支持多轮 `requestState` / `inputResponses` 透传。

        Args:
            name: prompt 名。
            arguments: 模板参数。
            request_state: 多轮请求状态。
            input_responses: 多轮输入回答。

        Returns:
            含 `messages` 的响应（或 `input_required`）。

        English
        --------
        Call `prompts/get`; pass through multi-round `requestState` /
        `inputResponses` when supplied.

        Args:
            name: prompt name.
            arguments: template arguments.
            request_state: multi-round request state.
            input_responses: multi-round input answers.

        Returns:
            response with `messages` (or `input_required`).
        """
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        if request_state:
            params["requestState"] = request_state
        if input_responses:
            params["inputResponses"] = {key: dict(value) for key, value in input_responses.items()}
        return await self.request("prompts/get", params)

    async def complete(self, reference: Mapping[str, Any], argument: Mapping[str, str]) -> Mapping[str, Any]:
        """中文
        ----
        调用 `completion/complete`。

        Args:
            reference: 待补全的 prompt / 资源模板引用。
            argument: 当前已输入的补全参数。

        Returns:
            含 `completion.values` 的响应。

        English
        --------
        Call `completion/complete`.

        Args:
            reference: the prompt / resource template reference to
                complete.
            argument: the currently-typed completion argument.

        Returns:
            response containing `completion.values`.
        """
        return await self.request("completion/complete", {"ref": dict(reference), "argument": dict(argument)})

    async def request(self, method: str, params: Mapping[str, Any] | None = None, *, use_cache: bool = True) -> Mapping[str, Any]:
        """中文
        ----
        通用请求入口：缓存 → 自增 id → 通过 `Exchange` 发送 → 解码 result
        → 写回缓存（`input_required` 永不缓存）。

        Args:
            method: 远端方法名。
            params: 业务参数。
            use_cache: `False` 时绕过本地缓存。

        Returns:
            业务 result。

        Raises:
            McpError: 服务端返回 error、`resultType` 非法、`Exchange` 返回
                `None`、或分页游标重复。

        English
        --------
        Generic request entry: cache → bump id → send via `Exchange` →
        decode result → write back cache (`input_required` never
        cached).

        Args:
            method: remote method name.
            params: business parameters.
            use_cache: when `False`, bypass the local cache.

        Returns:
            business result.

        Raises:
            McpError: server returns an error, `resultType` is
                invalid, `Exchange` returns `None`, or a pagination
                cursor repeats.
        """
        raw_params = dict(params or {})
        cache_key = self._cache_key(method, raw_params) if use_cache else None
        if cache_key is not None:
            cached = self._response_cache.get(cache_key)
            if cached is not None:
                return cached
        self._next_id += 1
        response = await self._exchange(self._dialect.encode_request(
            request_id=self._next_id + self._request_id_offset,
            method=method,
            params=raw_params,
            identity=self._identity,
            capabilities=self._capabilities,
        ))
        if response is None:
            raise McpError(-32603, "Request unexpectedly produced no response")
        if "error" in response:
            error = response["error"]
            if isinstance(error, Mapping):
                data = error.get("data")
                raise McpError(int(error.get("code", -32603)), str(error.get("message", "Unknown error")), data if isinstance(data, Mapping) else None)
            raise McpError(-32603, "Invalid error response")
        result = self._dialect.decode_result(response)
        if cache_key is not None:
            self._cache_response(cache_key, method, result)
        return result

    async def _paginate(self, method: str, result_key: str) -> AsyncIterator[Mapping[str, Any]]:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            result = await self.request(method, _cursor(cursor))
            values = result.get(result_key)
            if not isinstance(values, list) or any(not isinstance(value, Mapping) for value in values):
                raise McpError(-32603, "Invalid paginated MCP response", {"method": method, "key": result_key})
            for value in values:
                yield value
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise McpError(-32603, "Invalid MCP pagination cursor", {"method": method})
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def _cache_key(self, method: str, params: Mapping[str, Any]) -> str | None:
        if method not in _CACHEABLE_METHODS:
            return None
        serialized_params = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        partition = self._cache_partition or "public-only"
        return f"{self._dialect.version}|{self._identity.name}|{method}|{partition}|{serialized_params}"

    def _cache_response(self, key: str, method: str, result: Mapping[str, Any]) -> None:
        if result.get("resultType") == "input_required" or method not in _CACHEABLE_METHODS:
            return
        scope = result.get("cacheScope")
        ttl_ms = result.get("ttlMs")
        if scope not in {_PUBLIC_CACHE_SCOPE, _PRIVATE_CACHE_SCOPE} or isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
            return
        if scope == _PRIVATE_CACHE_SCOPE and self._cache_partition is None:
            return
        self._response_cache.put(key, result, ttl_ms=ttl_ms)


def _cursor(cursor: str | None) -> dict[str, str]:
    return {"cursor": cursor} if cursor else {}
