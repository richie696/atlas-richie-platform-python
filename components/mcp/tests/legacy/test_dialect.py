import unittest

from atlas_richie.mcp import InputRequired, McpClient, McpError, McpServer, ToolContext
from atlas_richie.mcp.legacy import LegacyMcpClientDialect, LegacyMcpServerDialect


class LegacyDialectContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_and_implicit_complete_map_to_modern_facades(self) -> None:
        server = McpServer(dialect=LegacyMcpServerDialect())

        @server.tool(name="ping")
        def ping(_context: ToolContext) -> str:
            return "pong"

        client = McpClient(server.handle, dialect=LegacyMcpClientDialect())
        discovery = await client.discover()
        invocation = await client.call_tool("ping")

        self.assertEqual("complete", discovery["resultType"])
        self.assertEqual(["2025-11-25"], discovery["supportedVersions"])
        self.assertEqual("pong", invocation["content"][0]["text"])

    async def test_legacy_rejects_multi_round_results(self) -> None:
        server = McpServer(dialect=LegacyMcpServerDialect())

        @server.tool(name="approval")
        def approval(_context: ToolContext) -> InputRequired:
            return InputRequired(request_state="unsupported-by-legacy")

        client = McpClient(server.handle, dialect=LegacyMcpClientDialect())
        with self.assertRaises(McpError) as captured:
            await client.call_tool("approval")

        self.assertEqual(-32602, captured.exception.code)


if __name__ == "__main__":
    unittest.main()
