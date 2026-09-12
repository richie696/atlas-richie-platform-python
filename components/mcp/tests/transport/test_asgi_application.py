import asyncio
import json
import unittest

from atlas_richie.mcp import InputRequired, McpServer, MrtRequestStateCodec, MrtStateBinding, ProgressUpdate, ToolContext
from atlas_richie.mcp.transport.asgi import McpAsgiApplication


class AsgiApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_maps_valid_mcp_headers_body_and_response(self) -> None:
        server = McpServer()
        @server.tool()
        def ping(_context: ToolContext) -> str:
            return "pong"
        app = McpAsgiApplication(server)
        messages = await _call(app, _request("tools/call", {"name": "ping"}))
        self.assertEqual(200, messages[0]["status"])
        self.assertEqual("pong", json.loads(messages[1]["body"])["result"]["content"][0]["text"])

    async def test_missing_mirror_header_is_rejected_before_dispatch(self) -> None:
        server = McpServer()
        messages = await _call(McpAsgiApplication(server), _request("tools/list", {}, method_header=None))
        self.assertEqual(400, messages[0]["status"])

    async def test_mismatched_name_header_is_rejected_before_dispatch(self) -> None:
        server = McpServer()
        request = _request("tools/call", {"name": "ping"})
        request["scope"]["headers"] = [(key, b"other" if key == b"mcp-name" else value) for key, value in request["scope"]["headers"]]
        messages = await _call(McpAsgiApplication(server), request)
        self.assertEqual(400, messages[0]["status"])

    async def test_progress_token_streams_notifications_before_the_final_response(self) -> None:
        server = McpServer()

        @server.tool(name="long-task")
        async def long_task(context: ToolContext) -> dict[str, bool]:
            assert context.progress is not None
            context.progress.report(ProgressUpdate(progress=0.5, total=1, message="halfway"))
            await asyncio.sleep(0)
            return {"complete": True}

        messages = await _call(
            McpAsgiApplication(server),
            _request("tools/call", {"name": "long-task", "progressToken": "progress-1"}),
        )

        self.assertEqual(b"text/event-stream", dict(messages[0]["headers"])[b"content-type"])
        events = _sse_payloads(messages)
        self.assertEqual("notifications/progress", events[0]["method"])
        self.assertEqual("progress-1", events[0]["params"]["progressToken"])
        self.assertEqual({"complete": True}, events[1]["result"]["structuredContent"])
        self.assertFalse(messages[-1]["more_body"])

    async def test_subscription_receives_selected_change_and_disconnect_releases_it(self) -> None:
        server = McpServer()
        app = McpAsgiApplication(server)
        connection = _Connection(_request("subscriptions/listen", {"notifications": {"toolsListChanged": True, "resourceSubscriptions": ["memo://status"]}}))
        task = asyncio.create_task(app(connection.scope, connection.receive, connection.send))
        await connection.started.wait()

        @server.tool(name="changed-tool")
        def changed_tool(_context: ToolContext) -> str:
            return "registered"

        app.subscriptions.resource_updated("memo://status")
        await _eventually(lambda: len(_sse_payloads(connection.sent)) == 3)
        await connection.events.put({"type": "http.disconnect"})
        await task

        events = _sse_payloads(connection.sent)
        self.assertEqual("notifications/subscriptions/acknowledged", events[0]["method"])
        self.assertEqual("notifications/tools/list_changed", events[1]["method"])
        self.assertEqual("notifications/resources/updated", events[2]["method"])
        self.assertEqual("memo://status", events[2]["params"]["uri"])

    async def test_asgi_transport_rehydrates_verified_mrtr_state_for_the_handler(self) -> None:
        context = ToolContext(principal_id="service-a")
        binding = MrtStateBinding(
            MrtRequestStateCodec(b"m" * 32),
            resource="https://inventory.example/mcp",
            principal_fingerprint=lambda value: f"principal:{value.principal_id}",
        )
        server = McpServer(context_factory=lambda _meta: context, mrtr_state=binding)

        @server.tool(name="approval")
        def approval(call_context: ToolContext) -> InputRequired | dict[str, str]:
            if call_context.request_state is None:
                return InputRequired(request_state="application-private-state")
            return {"continuation": call_context.request_state}

        app = McpAsgiApplication(server)
        initial = await _call(app, _request("tools/call", {"name": "approval"}))
        wire_state = json.loads(initial[1]["body"])["result"]["requestState"]
        resumed = await _call(app, _request("tools/call", {"name": "approval", "requestState": wire_state}))

        self.assertEqual("application-private-state", json.loads(resumed[1]["body"])["result"]["structuredContent"]["continuation"])


async def _call(app, request):
    connection = _Connection(request)
    await app(connection.scope, connection.receive, connection.send)
    return connection.sent


class _Connection:
    def __init__(self, request):
        self.scope = request["scope"]
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.events.put_nowait({"type": "http.request", "body": request["body"], "more_body": False})
        self.sent = []
        self.started = asyncio.Event()

    async def receive(self):
        return await self.events.get()

    async def send(self, value):
        self.sent.append(value)
        if value.get("type") == "http.response.start":
            self.started.set()


async def _eventually(predicate):
    for _ in range(10):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not met")


def _sse_payloads(messages):
    payloads = []
    for message in messages:
        body = message.get("body", b"")
        if isinstance(body, bytes) and body.startswith(b"event: message\n"):
            payloads.append(json.loads(body.decode().split("data: ", 1)[1].strip()))
    return payloads


def _request(method, params, method_header="present"):
    wire = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}}
    headers = [(b"content-type", b"application/json"), (b"accept", b"application/json, text/event-stream"), (b"mcp-protocol-version", b"2026-07-28")]
    if method_header is not None:
        headers.append((b"mcp-method", method.encode()))
    if method in {"tools/call", "prompts/get"}:
        headers.append((b"mcp-name", params["name"].encode()))
    return {"scope": {"type": "http", "method": "POST", "headers": headers}, "body": json.dumps(wire).encode()}


if __name__ == "__main__":
    unittest.main()
