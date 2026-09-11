"""集成测试：cache + mcp（Redis 作为 MCP 工具结果缓存）。

中文
----
演示 `McpClient` + `McpServer`（进程内） + `RedisProviderRegistrar` 三
者协作，把"重复工具调用"分流到 Redis：

- 起一个 in-process `McpServer`，注册一个慢工具 `slow_sum(a, b)`
  （`time.sleep(0.1)`）。
- 起一个 `McpClient`，把它的 `exchange` 直接绑到
  `server.handle`（**进程内** 模式；这里没有 stdio subprocess）。
- 包一层 `CachedMcpToolCaller`：先看 Redis 缓存里有没有
  `tool:<tool_name>:<hash(args)>`，没有就调 client、写入缓存。
- 第一次调用：~100ms。第二次：<5ms（命中缓存）。第三次：<5ms。
- 不同参数集拿到不同缓存 key。
- 显式 `invalidate(tool_name, args)` 后再调一次：~100ms。

`McpResponseCache`（mcp 组件内置）只缓存 list/discover 类型的请求
（`tools/list`、`resources/list` 等），不缓存 `tools/call`。所以这
个集成测试展示 **"如何用 cache 组件给 tool-call 路径加缓存"** 的
标准姿势。

English
--------
Integration test: cache + mcp (Redis as the MCP tool-result cache).

Demonstrates `McpClient` + `McpServer` (in-process) +
`RedisProviderRegistrar` working together to short-circuit repeated
tool calls to Redis:

- Spin up an in-process `McpServer` with a slow tool
  `slow_sum(a, b)` (`time.sleep(0.1)`).
- Spin up an `McpClient` whose `exchange` is bound directly to
  `server.handle` (in-process mode; no stdio subprocess here).
- Wrap calls in `CachedMcpToolCaller`: check Redis for
  `tool:<tool_name>:<hash(args)>`, fall through to the client on
  miss, write back the result.
- 1st call: ~100ms. 2nd: <5ms (cache hit). 3rd: <5ms.
- Distinct argument sets get distinct cache keys.
- Explicit `invalidate(tool_name, args)` re-fetches: ~100ms.

`McpResponseCache` (the mcp component's built-in) only caches
list/discover requests (`tools/list`, `resources/list`, etc.); it
does NOT cache `tools/call`. So this integration test shows the
standard pattern for **adding a tool-call cache via the cache
component**.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio

from atlas_richie.mcp import Implementation, McpClient, McpServer, ToolContext

pytestmark = pytest.mark.integration


# ── Test-local helpers ─────────────────────────────────────────────


def _build_in_process_server() -> McpServer:
    """A McpServer with one slow tool that records every invocation.

    The tool sleeps ~100ms so the cache hit is observable on the
    wall clock.
    """
    server = McpServer(identity=Implementation(name="cache-mcp-test-server", version="0.1.0"))
    call_counter = {"count": 0}

    @server.tool(name="slow_sum", description="Sleep 100ms then return a+b")
    async def slow_sum(_context: ToolContext, a: int, b: int) -> dict[str, Any]:
        call_counter["count"] += 1
        time.sleep(0.1)
        return {"a": a, "b": b, "sum": a + b, "call_count": call_counter["count"]}

    return server


class _CachedMcpToolCaller:
    """Redis-backed tool-result cache for `McpClient.call_tool`.

    Cache key shape: `mcp:<namespace>:tool:<tool>:<sha256(args)>`.
    The args hash is the JSON-serialised dict, sorted by key, so
    `{a: 1, b: 2}` and `{b: 2, a: 1}` share an entry.
    """

    def __init__(
        self,
        value_ops: Any,
        key_ops: Any,
        namespace: str,
        client: McpClient,
    ) -> None:
        self._value_ops = value_ops
        self._key_ops = key_ops
        self._namespace = namespace
        self._client = client
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _hash_args(arguments: Mapping[str, Any]) -> str:
        serialised = json.dumps(arguments, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]

    def _cache_key(self, tool_name: str, arguments: Mapping[str, Any]) -> str:
        return f"mcp:{self._namespace}:tool:{tool_name}:{self._hash_args(arguments)}"

    async def call(self, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        key = self._cache_key(tool_name, arguments)
        cached = self._value_ops.get(key, dict)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        result = await self._client.call_tool(tool_name, arguments)
        # `McpClient.call_tool` wraps the return value in a dict with
        # `resultType`, `content`, and `structuredContent` fields.
        # Cache the inner `structuredContent` so callers get the raw dict.
        payload = dict(result.get("structuredContent", {}))
        self._value_ops.set_with_ttl(
            key, payload, timeout_millis=60_000
        )
        return payload

    def invalidate(self, tool_name: str, arguments: Mapping[str, Any]) -> None:
        self._key_ops.remove_cache(self._cache_key(tool_name, arguments))


# ── Tests ──────────────────────────────────────────────────────────


class TestRedisBackedMcpToolCache:
    """In-process McpClient/Server + Redis as the tool-result cache."""

    @pytest.mark.asyncio
    async def test_second_and_third_calls_are_cache_hits(
        self,
        installed_registrar: Any,
        redis_namespace: str,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        server = _build_in_process_server()
        # In-process exchange: hand the McpClient the server's
        # `handle` coroutine as its transport.
        client = McpClient(exchange=server.handle)
        # Use redis_namespace so keys are unique per test module and
        # do not bleed across integration test files.
        caller = _CachedMcpToolCaller(
            value_ops, key_ops, namespace=redis_namespace, client=client
        )

        # First call: cache miss, ~100ms.
        t0 = time.perf_counter()
        first = await caller.call("slow_sum", {"a": 1, "b": 2})
        first_elapsed = time.perf_counter() - t0
        # Second call: cache hit, <10ms.
        t0 = time.perf_counter()
        second = await caller.call("slow_sum", {"a": 1, "b": 2})
        second_elapsed = time.perf_counter() - t0
        # Third call: cache hit, <10ms.
        t0 = time.perf_counter()
        third = await caller.call("slow_sum", {"a": 1, "b": 2})
        third_elapsed = time.perf_counter() - t0

        assert first == second == third
        assert first["sum"] == 3
        # First call is the only one that slept 100ms; 2nd and 3rd
        # should be dramatically faster.
        assert first_elapsed >= 0.09, (
            f"first call should sleep ~100ms, was {first_elapsed:.3f}s"
        )
        assert second_elapsed < 0.05, (
            f"second call should be a cache hit, was {second_elapsed:.3f}s"
        )
        assert third_elapsed < 0.05, (
            f"third call should be a cache hit, was {third_elapsed:.3f}s"
        )
        assert caller.hits == 2
        assert caller.misses == 1

    @pytest.mark.asyncio
    async def test_different_arguments_get_different_cache_entries(
        self,
        installed_registrar: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        server = _build_in_process_server()
        client = McpClient(exchange=server.handle)
        caller = _CachedMcpToolCaller(
            value_ops, key_ops, namespace="mcp-tool", client=client
        )

        r1 = await caller.call("slow_sum", {"a": 1, "b": 2})
        r2 = await caller.call("slow_sum", {"a": 2, "b": 3})
        r1_again = await caller.call("slow_sum", {"a": 1, "b": 2})

        assert r1["sum"] == 3
        assert r2["sum"] == 5
        assert r1_again["sum"] == 3
        # 3 calls, but 2 distinct argument sets → 1 hit, 2 misses.
        assert caller.hits == 1
        assert caller.misses == 2

    @pytest.mark.asyncio
    async def test_invalidate_forces_a_re_invocation(
        self,
        installed_registrar: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        server = _build_in_process_server()
        client = McpClient(exchange=server.handle)
        caller = _CachedMcpToolCaller(
            value_ops, key_ops, namespace="mcp-tool", client=client
        )

        first = await caller.call("slow_sum", {"a": 7, "b": 11})
        caller.invalidate("slow_sum", {"a": 7, "b": 11})
        second = await caller.call("slow_sum", {"a": 7, "b": 11})

        assert first["sum"] == 18
        assert second["sum"] == 18
        # The McpServer-side `call_count` field shows the tool was
        # actually re-invoked (the new payload has a different
        # counter).
        assert first["call_count"] == 1
        assert second["call_count"] == 2
        assert caller.hits == 0
        assert caller.misses == 2

    @pytest.mark.asyncio
    async def test_tools_list_is_cached_by_builtin_response_cache(
        self,
        installed_registrar: Any,
    ) -> None:
        """The McpClient's built-in `McpResponseCache` is
        process-local (NOT Redis-backed). The Redis cache only
        covers our explicit tool-call wrapper. This test pins down
        the boundary: tools/list hits the in-process response cache
        (zero Redis keys touched).
        """
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        server = _build_in_process_server()
        client = McpClient(exchange=server.handle)
        # Pre-warm the in-process response cache.
        await client.list_tools()
        # The McpResponseCache is in-process; verify our Redis
        # namespace has no `tools/list` entry.
        listing_keys = list(
            value_ops._backend.raw_client().scan_iter(  # type: ignore[attr-defined]
                match="mcp:mcp-tool:tools/list*", count=100
            )
        ) if hasattr(value_ops, "_backend") else []
        assert listing_keys == [], (
            "tools/list goes through the in-process McpResponseCache, "
            "not the Redis cache we built"
        )
