import unittest

from atlas_richie.contracts import ValidationError
from atlas_richie.mcp import McpClient, McpError, McpServer, ToolContext
from atlas_richie.mcp.schema.jsonschema import JsonSchemaCompiler


class JsonSchemaCompilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_draft_2020_12_input_and_output_contracts_are_enforced(self) -> None:
        server = McpServer(schema_compiler=JsonSchemaCompiler())

        @server.tool(
            input_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            output_schema={"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
        )
        def typed(_context: ToolContext, name: str) -> dict[str, bool]:
            return {"ok": bool(name)}

        client = McpClient(server.handle)
        with self.assertRaises(McpError) as captured:
            await client.call_tool("typed", {"name": 3})
        self.assertEqual("input_schema_invalid", captured.exception.data["reason"])
        result = await client.call_tool("typed", {"name": "Ada"})
        self.assertEqual({"ok": True}, result["structuredContent"])

    def test_external_refs_are_rejected_without_network_resolution(self) -> None:
        with self.assertRaises(ValidationError):
            JsonSchemaCompiler().compile({"$ref": "https://example.invalid/schema.json"})


if __name__ == "__main__":
    unittest.main()
