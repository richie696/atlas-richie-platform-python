"""Transport-neutral MCP client facade for the stateless 2026-07-28 protocol."""

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
    """Owns client-side wire differences without leaking them into public operations."""

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
    """Current stateless MCP request and result mapping."""

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
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("resultType") not in {"complete", "input_required"}:
            raise McpError(-32603, "Invalid result response")
        return result


DEFAULT_CLIENT_DIALECT = ModernMcpClientDialect()


class McpClient:
    """Protocol facade; a transport adapter supplies the only network or process I/O."""

    def __init__(
        self,
        exchange: Exchange,
        *,
        identity: Implementation | None = None,
        capabilities: Mapping[str, Any] | None = None,
        response_cache: McpResponseCache | None = None,
        cache_partition: str | None = None,
        dialect: McpClientDialect = DEFAULT_CLIENT_DIALECT,
    ) -> None:
        self._exchange = exchange
        self._identity = identity or Implementation("atlas-richie-mcp-client", "0.1.0")
        self._capabilities = dict(capabilities or {})
        self._next_id = 0
        self._response_cache = response_cache or McpResponseCache()
        self._cache_partition = cache_partition
        self._dialect = dialect

    async def discover(self) -> Mapping[str, Any]:
        return await self.negotiate()

    async def negotiate(self, *, refresh: bool = False) -> Mapping[str, Any]:
        """Discover the remote modern capability profile, using its declared cache policy."""
        return await self.request("server/discover", use_cache=not refresh)

    def invalidate_cache(self) -> None:
        """Forget local discovery/list/read snapshots after an external invalidation signal."""
        self._response_cache.invalidate()

    async def list_tools(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        return await self.request("tools/list", _cursor(cursor))

    async def iter_tools(self) -> AsyncIterator[Mapping[str, Any]]:
        async for item in self._paginate("tools/list", "tools"):
            yield item

    async def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None, *, request_state: str | None = None, input_responses: Mapping[str, Mapping[str, Any]] | None = None) -> Mapping[str, Any]:
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        if request_state:
            params["requestState"] = request_state
        if input_responses:
            params["inputResponses"] = {key: dict(value) for key, value in input_responses.items()}
        return await self.request("tools/call", params)

    async def list_resources(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        return await self.request("resources/list", _cursor(cursor))

    async def iter_resources(self) -> AsyncIterator[Mapping[str, Any]]:
        async for item in self._paginate("resources/list", "resources"):
            yield item

    async def list_resource_templates(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        return await self.request("resources/templates/list", _cursor(cursor))

    async def iter_resource_templates(self) -> AsyncIterator[Mapping[str, Any]]:
        async for item in self._paginate("resources/templates/list", "resourceTemplates"):
            yield item

    async def read_resource(self, uri: str) -> Mapping[str, Any]:
        return await self.request("resources/read", {"uri": uri})

    async def list_prompts(self, *, cursor: str | None = None) -> Mapping[str, Any]:
        return await self.request("prompts/list", _cursor(cursor))

    async def iter_prompts(self) -> AsyncIterator[Mapping[str, Any]]:
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
        params: dict[str, Any] = {"name": name, "arguments": dict(arguments or {})}
        if request_state:
            params["requestState"] = request_state
        if input_responses:
            params["inputResponses"] = {key: dict(value) for key, value in input_responses.items()}
        return await self.request("prompts/get", params)

    async def complete(self, reference: Mapping[str, Any], argument: Mapping[str, str]) -> Mapping[str, Any]:
        return await self.request("completion/complete", {"ref": dict(reference), "argument": dict(argument)})

    async def request(self, method: str, params: Mapping[str, Any] | None = None, *, use_cache: bool = True) -> Mapping[str, Any]:
        raw_params = dict(params or {})
        cache_key = self._cache_key(method, raw_params) if use_cache else None
        if cache_key is not None:
            cached = self._response_cache.get(cache_key)
            if cached is not None:
                return cached
        self._next_id += 1
        response = await self._exchange(self._dialect.encode_request(
            request_id=self._next_id,
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
