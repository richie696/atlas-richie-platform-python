import unittest

from atlas_richie.http import HttpResponse
from atlas_richie.http.models import AsyncHttpStreamResponse
from atlas_richie.mcp_http import McpHttpExchange


class McpHttpExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_http_adapter_sets_protocol_and_mirror_headers(self) -> None:
        http = _Http()
        exchange = McpHttpExchange("https://peer.example/mcp", http, authorization="Bearer access")
        result = await exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "catalog.find"}})
        self.assertEqual("complete", result["resultType"])
        self.assertEqual("tools/call", http.request.headers["Mcp-Method"])
        self.assertEqual("catalog.find", http.request.headers["Mcp-Name"])
        self.assertEqual("Bearer access", http.request.headers["Authorization"])

    async def test_dpop_outbound_proof_is_bound_to_the_mcp_post_and_dpop_token(self) -> None:
        http = _Http()
        factory = _DpopFactory()
        exchange = McpHttpExchange("https://peer.example/mcp", http, authorization="DPoP access", dpop_proof_factory=factory)
        await exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual("proof-value", http.request.headers["DPoP"])
        self.assertEqual(("POST", "https://peer.example/mcp", "access"), factory.call)

    def test_dpop_outbound_refuses_a_bearer_token_or_missing_dpop_token(self) -> None:
        with self.assertRaises(ValueError):
            McpHttpExchange("https://peer.example/mcp", _Http(), authorization="Bearer access", dpop_proof_factory=_DpopFactory())

    async def test_authorization_provider_supplies_a_fresh_dpop_token_for_each_exchange(self) -> None:
        http = _Http()
        provider = _AuthorizationProvider()
        exchange = McpHttpExchange("https://peer.example/mcp", http, authorization_provider=provider, dpop_proof_factory=_DpopFactory())
        await exchange({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        self.assertEqual("DPoP dynamic-access", http.request.headers["Authorization"])
        self.assertEqual(1, provider.calls)


class _Http:
    def __init__(self) -> None:
        self.request = None
        self._body = b'{"resultType":"complete","content":[]}'
        self._headers = {"content-type": "application/json"}

    async def execute(self, request):
        self.request = request
        return HttpResponse(200, self._headers, self._body, request.method, request.url)

    async def open_stream(self, request):
        self.request = request
        body = self._body
        headers = self._headers

        async def _iter() -> bytes:
            yield body

        async def _close() -> None:
            return None

        return AsyncHttpStreamResponse(
            status_code=200,
            headers=headers,
            method=request.method,
            url=request.url,
            iter_bytes=_iter,
            close=_close,
        )


class _DpopFactory:
    def __init__(self):
        self.call = None

    def create(self, *, method, target_uri, access_token=None, nonce=None):  # type: ignore[no-untyped-def]
        self.call = (method, target_uri, access_token)
        return "proof-value"


class _AuthorizationProvider:
    def __init__(self):
        self.calls = 0

    def authorization_for(self):
        self.calls += 1
        return "DPoP dynamic-access"


if __name__ == "__main__":
    unittest.main()
