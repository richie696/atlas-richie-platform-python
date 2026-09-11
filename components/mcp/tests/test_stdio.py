import asyncio
import io
import json
import unittest

from atlas_richie.mcp import McpServer, ToolContext
from atlas_richie.mcp.stdio import decode_line, encode_line, serve_stdio


class StdioContractTests(unittest.TestCase):
    def test_round_trip_is_one_json_line(self) -> None:
        frame = encode_line({"message": "你好"})
        self.assertEqual(b'{"message":"\xe4\xbd\xa0\xe5\xa5\xbd"}\n', frame)
        self.assertEqual({"message": "你好"}, decode_line(frame))

    def test_malformed_line_is_a_protocol_error_frame(self) -> None:
        reader = io.BytesIO(b"not-json\n")
        writer = io.BytesIO()
        asyncio.run(serve_stdio(McpServer(), reader, writer))
        response = json.loads(writer.getvalue())
        self.assertEqual(-32700, response["error"]["code"])

    def test_stdout_contains_only_protocol_frames(self) -> None:
        server = McpServer()

        @server.tool()
        def ping(_context: ToolContext) -> str:
            return "pong"

        request = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "ping",
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        reader = io.BytesIO(encode_line(request))
        writer = io.BytesIO()
        asyncio.run(serve_stdio(server, reader, writer))
        lines = writer.getvalue().splitlines()
        self.assertEqual(1, len(lines))
        response = json.loads(lines[0])
        self.assertEqual("pong", response["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
