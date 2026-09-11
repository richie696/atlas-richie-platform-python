import asyncio
import unittest
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from atlas_richie.contracts import CapabilityUnavailable, ValidationError
from atlas_richie.mcp import (
    CompletionResult,
    InputRequired,
    McpClient,
    McpError,
    McpInvocation,
    McpRegistrySnapshot,
    McpServer,
    MrtRequestStateCodec,
    MrtStateBinding,
    ProgressUpdate,
    ToolContext,
)


class _InvocationRecorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


class _ProgressRecorder:
    def __init__(self) -> None:
        self.updates: list[ProgressUpdate] = []

    def report(self, update: ProgressUpdate) -> None:
        self.updates.append(update)


class _OrderingInterceptor:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def intercept(self, invocation: McpInvocation, proceed: Callable[[McpInvocation], Awaitable[object]]) -> object:
        self._events.append("caller-before")
        result = await proceed(invocation)
        self._events.append("caller-after")
        return result


class McpServerContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = McpServer(page_size=1)

        @self.server.tool(description="Returns a greeting.")
        def greet(_context: ToolContext, name: str) -> dict[str, str]:
            return {"greeting": f"Hello, {name}!"}

        @self.server.resource(uri="memo://welcome", name="welcome", mime_type="text/plain")
        def welcome(_context: ToolContext) -> str:
            return "Welcome"

        @self.server.resource(uri="memo://second", name="second")
        def second(_context: ToolContext) -> str:
            return "Second"

        @self.server.prompt(arguments=({"name": "name", "required": True},))
        def hello_prompt(_context: ToolContext, name: str) -> list[dict[str, object]]:
            return [{"role": "user", "content": {"type": "text", "text": f"Hello {name}"}}]

        @self.server.prompt(name="approval")
        def approval(_context: ToolContext) -> InputRequired:
            return InputRequired(request_state="opaque-state")

        @self.server.tool(name="resume")
        def resume(context: ToolContext) -> dict[str, object]:
            return {"state": context.request_state, "responses": dict(context.input_responses)}

        @self.server.completion
        def complete(_context: ToolContext, _reference: dict[str, object], _argument: dict[str, str]) -> CompletionResult:
            return CompletionResult(("Ada",), total=1, has_more=False)

        self.greet = greet
        self.client = McpClient(self.server.handle)

    async def test_discovery_and_tool_invocation_use_public_facades(self) -> None:
        discovery = await self.client.discover()
        self.assertEqual(["2026-07-28"], discovery["supportedVersions"])
        self.assertIn("resources", discovery["capabilities"])
        self.assertEqual("complete", discovery["resultType"])
        self.assertEqual("atlas-richie-mcp", discovery["_meta"]["io.modelcontextprotocol/serverInfo"]["name"])
        tools = await self.client.list_tools()
        self.assertEqual("greet", tools["tools"][0]["name"])
        self.assertEqual("private", tools["cacheScope"])
        invocation = await self.client.call_tool("greet", {"name": "Ada"})
        self.assertEqual({"greeting": "Hello, Ada!"}, invocation["structuredContent"])
        self.assertEqual({"greeting": "Hello, Ada!"}, self.greet(ToolContext(), "Ada"))

    async def test_resource_prompt_completion_pagination_and_mrtr_are_protocol_results(self) -> None:
        first_page = await self.client.list_resources()
        self.assertEqual(1, len(first_page["resources"]))
        self.assertIn("nextCursor", first_page)
        second_page = await self.client.list_resources(cursor=first_page["nextCursor"])
        self.assertEqual(1, len(second_page["resources"]))
        resource = await self.client.read_resource("memo://welcome")
        self.assertEqual("Welcome", resource["contents"][0]["text"])
        prompt = await self.client.get_prompt("hello_prompt", {"name": "Ada"})
        self.assertEqual("Hello Ada", prompt["messages"][0]["content"]["text"])
        interactive = await self.client.get_prompt("approval")
        self.assertEqual("input_required", interactive["resultType"])
        self.assertEqual("opaque-state", interactive["requestState"])
        resumed = await self.client.call_tool("resume", request_state="opaque-state", input_responses={"request-1": {"result": "approved"}})
        self.assertEqual("opaque-state", resumed["structuredContent"]["state"])
        completion = await self.client.complete({"type": "ref/prompt", "name": "hello_prompt"}, {"name": "A"})
        self.assertEqual(["Ada"], completion["completion"]["values"])

    async def test_modern_metadata_and_unknown_method_are_controlled_errors(self) -> None:
        response = await self.server.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}})
        assert response is not None
        self.assertEqual("modern_meta_required", response["error"]["data"]["reason"])
        with self.assertRaises(McpError) as captured:
            await self.client.request("not/a/method")
        self.assertEqual(-32601, captured.exception.code)

    async def test_unchecked_schema_fails_closed(self) -> None:
        with self.assertRaises(CapabilityUnavailable):
            @self.server.tool(input_schema={"type": "object"})
            def unsafe(_context: ToolContext) -> str:
                return "never registered"

    async def test_duplicate_tool_names_and_missing_scope_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            @self.server.tool(name="greet")
            def duplicate(_context: ToolContext) -> str:
                return "duplicate"
        secured = McpServer(context_factory=lambda _meta: ToolContext(granted_scopes=frozenset()))
        @secured.tool(required_scopes=frozenset({"report:read"}))
        def report(_context: ToolContext) -> str:
            return "secret"
        with self.assertRaises(McpError) as captured:
            await McpClient(secured.handle).call_tool("report")
        self.assertEqual(-32003, captured.exception.code)

    async def test_header_version_mismatch_and_notifications_do_not_leak_a_response(self) -> None:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}}
        response = await self.server.handle(payload, transport_version="2025-11-25")
        assert response is not None
        self.assertEqual(-32020, response["error"]["code"])
        self.assertIsNone(await self.server.handle({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}))

    async def test_cancellation_is_cooperative_and_scoped_to_one_active_invocation(self) -> None:
        started = asyncio.Event()
        continue_handler = asyncio.Event()
        server = McpServer()

        @server.tool(name="cancellable")
        async def cancellable(context: ToolContext) -> dict[str, bool]:
            started.set()
            await continue_handler.wait()
            return {"cancelled": context.cancellation.is_cancelled}

        client = McpClient(server.handle)
        pending = asyncio.create_task(client.call_tool("cancellable"))
        await started.wait()
        self.assertIsNone(
            await server.handle(
                {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
            )
        )
        continue_handler.set()
        result = await pending

        self.assertEqual({"cancelled": True}, result["structuredContent"])

    async def test_registry_reload_replaces_one_snapshot_and_notifies_listeners(self) -> None:
        revisions = []
        remove_listener = self.server.add_registry_listener(lambda change: revisions.append(change.current_revision))
        initial = self.server.registry_snapshot
        self.server.reload(McpRegistrySnapshot(
            revision=0,
            tools={}, resources={}, resource_templates={}, prompts={},
        ))
        remove_listener()

        self.assertGreater(self.server.registry_snapshot.revision, initial.revision)
        self.assertEqual([self.server.registry_snapshot.revision], revisions)
        self.assertEqual([], (await self.client.list_tools())["tools"])
        with self.assertRaises(McpError) as captured:
            await self.client.complete({"type": "ref/prompt", "name": "hello_prompt"}, {"name": "A"})
        self.assertEqual(-32601, captured.exception.code)

    async def test_tool_invocation_has_ordered_trace_deadline_caller_audit_and_progress_ports(self) -> None:
        events: list[str] = []
        audits = _InvocationRecorder()
        traces = _InvocationRecorder()
        progress = _ProgressRecorder()
        server = McpServer(
            context_factory=lambda _meta: ToolContext(trace_id="trace-123", progress=progress),
            invocation_interceptors=(_OrderingInterceptor(events),),
            audit_sink=audits,
            trace_sink=traces,
        )

        @server.tool(name="monitored")
        def monitored(context: ToolContext) -> dict[str, bool]:
            events.append("handler")
            assert context.progress is not None
            context.progress.report(ProgressUpdate(progress=1, total=1, message="complete"))
            return {"ok": True}

        result = await McpClient(server.handle).call_tool("monitored")

        self.assertEqual({"ok": True}, result["structuredContent"])
        self.assertEqual(["caller-before", "handler", "caller-after"], events)
        self.assertEqual(["start", "end"], [event.phase for event in traces.events])
        self.assertEqual("trace-123", traces.events[0].trace_id)
        self.assertEqual("success", audits.events[0].outcome)
        self.assertEqual([ProgressUpdate(progress=1, total=1, message="complete")], progress.updates)

        expired = McpServer(context_factory=lambda _meta: ToolContext(deadline=datetime.now(UTC) - timedelta(seconds=1)))

        @expired.tool(name="expired")
        def should_not_run(_context: ToolContext) -> str:
            self.fail("expired invocation must not reach the handler")

        rejected = await McpClient(expired.handle).call_tool("expired")
        self.assertTrue(rejected["isError"])

    async def test_signed_mrtr_state_restores_only_the_bound_continuation_and_rejects_stale_registry(self) -> None:
        context = ToolContext(principal_id="service-a", tenant_id="tenant-a", granted_scopes=frozenset({"inventory.read"}))
        state = MrtStateBinding(
            MrtRequestStateCodec(b"m" * 32),
            resource="https://inventory.example/mcp",
            principal_fingerprint=lambda value: f"principal:{value.principal_id}",
        )
        server = McpServer(context_factory=lambda _meta: context, mrtr_state=state)

        @server.tool(name="approval")
        def approval(call_context: ToolContext) -> InputRequired | dict[str, object]:
            if call_context.request_state is None:
                return InputRequired({"approve": {"type": "boolean"}}, "application-private-state")
            return {"continuation": call_context.request_state, "responses": dict(call_context.input_responses)}

        client = McpClient(server.handle)
        pending = await client.call_tool("approval")
        wire_state = pending["requestState"]
        self.assertIsInstance(wire_state, str)
        self.assertNotEqual("application-private-state", wire_state)
        resumed = await client.call_tool("approval", request_state=wire_state, input_responses={"approve": {"value": True}})
        self.assertEqual("application-private-state", resumed["structuredContent"]["continuation"])

        snapshot = server.registry_snapshot
        server.reload(McpRegistrySnapshot(0, snapshot.tools, snapshot.resources, snapshot.resource_templates, snapshot.prompts))
        with self.assertRaises(McpError) as captured:
            await client.call_tool("approval", request_state=wire_state)
        self.assertEqual(-32602, captured.exception.code)
        self.assertEqual("invalid_request_state", captured.exception.data["reason"])


if __name__ == "__main__":
    unittest.main()
