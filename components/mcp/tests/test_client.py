import unittest
from collections.abc import Mapping
from typing import Any

from atlas_richie.mcp import McpClient


class _RecordingExchange:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, Any]] = []

    async def __call__(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(payload)
        method = payload["method"]
        params = payload["params"]
        if method == "server/discover":
            return _response(payload, {"resultType": "complete", "cacheScope": "public", "ttlMs": 60_000})
        if method == "tools/list":
            cursor = params.get("cursor")
            if cursor is None:
                result = {"resultType": "complete", "cacheScope": "private", "ttlMs": 60_000, "tools": [{"name": "first"}], "nextCursor": "page-2"}
            else:
                result = {"resultType": "complete", "cacheScope": "private", "ttlMs": 60_000, "tools": [{"name": "second"}]}
            return _response(payload, result)
        raise AssertionError(f"unexpected method: {method}")


class McpClientContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_cache_explicit_invalidation_and_private_partition(self) -> None:
        exchange = _RecordingExchange()
        client = McpClient(exchange)

        await client.negotiate()
        await client.discover()
        self.assertEqual(1, len(exchange.calls))
        await client.negotiate(refresh=True)
        self.assertEqual(2, len(exchange.calls))
        client.invalidate_cache()
        await client.discover()
        self.assertEqual(3, len(exchange.calls))

        await client.list_tools()
        await client.list_tools()
        self.assertEqual(5, len(exchange.calls))

        private_client = McpClient(exchange, cache_partition="tenant-a:principal-fingerprint")
        await private_client.list_tools()
        await private_client.list_tools()
        self.assertEqual(6, len(exchange.calls))

    async def test_async_pagination_fetches_each_page_once_and_rejects_cycles(self) -> None:
        exchange = _RecordingExchange()
        client = McpClient(exchange, cache_partition="tenant-a:principal-fingerprint")

        names = [tool["name"] async for tool in client.iter_tools()]

        self.assertEqual(["first", "second"], names)
        self.assertEqual(["tools/list", "tools/list"], [call["method"] for call in exchange.calls])


def _response(payload: Mapping[str, Any], result: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"jsonrpc": "2.0", "id": payload["id"], "result": dict(result)}
