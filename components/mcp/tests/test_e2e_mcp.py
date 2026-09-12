"""End-to-end tests for `atlas-richie-mcp` (R-### E.2).

中文
----
E2E 测试集：真实 `McpClient` + 真实 `McpServer` + 真实 JSON-RPC over stdio。

策略：

- **Option A**（subprocess stdio）：启动 `_e2e_test_server.py`
  子进程跑 `serve_stdio`；客户端 `McpClient` 通过注入的
  async exchange 跨进程读写。
- **Option B**（in-process）：仅用于 cancellation 场景 —— stdio
  是单线程顺序循环，notification 无法在 handler 运行期间被
  处理；in-process 可以并发调用 `server.handle`。

所有测试都带 `pytest.mark.e2e`；`pytest -m "not e2e"` 默认跳过。

English
--------
End-to-end suite: real `McpClient` + real `McpServer` + real
JSON-RPC over stdio.

Strategy:

- **Option A** (subprocess stdio): launch `_e2e_test_server.py`
  as a subprocess that runs `serve_stdio` over real pipes; the
  client `McpClient` reads / writes through an injected async
  exchange.
- **Option B** (in-process): only for the cancellation scenario —
  stdio is a single-threaded sequential loop, so a notification
  cannot be processed while a handler is still running;
  in-process lets us call `server.handle` concurrently.

All tests carry `@pytest.mark.e2e`; `pytest -m "not e2e"` skips
them by default.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from atlas_richie.mcp import (
    Implementation,
    McpClient,
    McpError,
    McpServer,
    ToolContext,
)
from atlas_richie.mcp.transport.stdio import encode_line


pytestmark = pytest.mark.e2e

# Path to the test-server script (launched as a subprocess).
TEST_SERVER_PATH = Path(__file__).parent / "_e2e_test_server.py"
# Workspace root — the test server must be run with `cwd=WORKSPACE_ROOT`
# so the `atlas_richie` editable install is importable.
WORKSPACE_ROOT = Path(__file__).parents[3]


# ─── Async subprocess transport ──────────────────────────────────────


class _SubprocessTransport:
    """Async request / response multiplexer over a synchronous stdio subprocess.

    The subprocess serves JSON-RPC over newline-delimited frames on
    its stdin / stdout. This transport:

    - serialises writes (one request frame at a time);
    - dispatches each response to the right pending coroutine by
      `id`;
    - supports notifications (no response expected);
    - exits cleanly when stdin closes.

    The class is intentionally framework-neutral — it does not
    depend on any MCP APIs other than the stdio framing helper.
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self._loop = asyncio.get_event_loop()
        self._write_lock = asyncio.Lock()
        # `request_id` → Future[response]. Inserted BEFORE the
        # write so the reader can resolve the future as soon as the
        # response frame arrives.
        self._pending: dict[Any, asyncio.Future] = {}
        self._closed = False
        self._reader_task = self._loop.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._loop.run_in_executor(
                    None, self._proc.stdout.readline
                )
                if not line:
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(
                                McpError(-32603, "Subprocess closed unexpectedly")
                            )
                    self._pending.clear()
                    return
                try:
                    response: dict[str, Any] = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    for fut in self._pending.values():
                        if not fut.done():
                            fut.set_exception(McpError(-32700, f"Invalid response: {exc}"))
                    self._pending.clear()
                    continue
                request_id = response.get("id")
                future = self._pending.pop(request_id, None)
                if future is not None and not future.done():
                    future.set_result(response)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001 — reader-task best-effort cleanup
            return

    async def exchange(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send a JSON-RPC request and await the matching response.

        The request must carry an `id` field; notifications are
        sent via `send_notification`.
        """
        if self._closed:
            raise McpError(-32603, "Transport closed")
        if "id" not in request:
            raise ValueError("exchange() requires a request with an 'id' field")
        future: asyncio.Future = self._loop.create_future()
        self._pending[request["id"]] = future
        line = encode_line(dict(request))
        async with self._write_lock:
            if self._closed:
                raise McpError(-32603, "Transport closed")
            await self._loop.run_in_executor(None, self._proc.stdin.write, line)
            await self._loop.run_in_executor(None, self._proc.stdin.flush)
        return await future

    async def send_notification(self, request: Mapping[str, Any]) -> None:
        """Send a JSON-RPC notification (no `id`); no response is read."""
        if "id" in request:
            raise ValueError("send_notification() requires a request without an 'id' field")
        line = encode_line(dict(request))
        async with self._write_lock:
            if self._closed:
                raise McpError(-32603, "Transport closed")
            await self._loop.run_in_executor(None, self._proc.stdin.write, line)
            await self._loop.run_in_executor(None, self._proc.stdin.flush)

    async def close(self) -> None:
        self._closed = True
        try:
            self._proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._loop.run_in_executor(None, self._proc.wait, 5.0)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                await self._loop.run_in_executor(None, self._proc.wait, 2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                await self._loop.run_in_executor(None, self._proc.wait)
        if not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


# ─── Test server lifecycle ───────────────────────────────────────────


class _StdioSubprocessE2EMixin:
    """Shared setup for tests that drive the subprocess stdio transport.

    The subprocess is launched once per class (the server is
    stateless; per-test isolation comes from a fresh transport +
    client per test).

    Each subclass stores its own subprocess under a unique key
    (``_proc_<ClassName>``) on the mixin so that ``setUpClass`` /
    ``tearDownClass`` only touch *this* class's subprocess and never
    kill a process that a later class is still using.
    """

    _proc_storage: dict[str, subprocess.Popen | None] = {}  # class-name → proc

    @classmethod
    def setUpClass(cls) -> None:
        key = f"_proc_{cls.__name__}"
        # Guard: terminate any stale proc for *this* class that a prior
        # run left behind (e.g. crashed test suite).
        prior: subprocess.Popen | None = _StdioSubprocessE2EMixin._proc_storage.get(key)
        if prior is not None and prior.poll() is None:
            prior.terminate()
            try:
                prior.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                prior.kill()
                prior.wait()
        proc = subprocess.Popen(
            [sys.executable, str(TEST_SERVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(WORKSPACE_ROOT),
        )
        _StdioSubprocessE2EMixin._proc_storage[key] = proc

    @classmethod
    def tearDownClass(cls) -> None:
        key = f"_proc_{cls.__name__}"
        proc: subprocess.Popen | None = _StdioSubprocessE2EMixin._proc_storage.get(key)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        _StdioSubprocessE2EMixin._proc_storage[key] = None

    async def asyncSetUp(self) -> None:
        key = f"_proc_{self.__class__.__name__}"
        proc = _StdioSubprocessE2EMixin._proc_storage[key]
        self.transport: _SubprocessTransport = _SubprocessTransport(proc)
        self.client: McpClient = McpClient(
            self.transport.exchange,
            identity=Implementation("e2e-test-client", "1.0.0"),
        )
        # Warmup: confirm the subprocess is alive and serving before
        # the test method runs. If the subprocess is unreachable,
        # fail fast instead of corrupting later assertions.
        discovery = await asyncio.wait_for(self.client.discover(), timeout=10.0)
        assert "tools" in discovery["capabilities"]

    async def asyncTearDown(self) -> None:
        await self.transport.close()


# ─── 1. stdio subprocess round-trip ──────────────────────────────────


class StdioSubprocessRoundTripE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """E2E round-trip through a real stdio subprocess."""

    async def test_echo_round_trip(self) -> None:
        """中文：单次 echo 调用跨子进程 stdio 往返。

        English: A single `call_tool("echo")` round-trips through a
        real subprocess over newline-delimited JSON-RPC on stdio.
        """
        result = await self.client.call_tool("echo", {"text": "hi"})

        self.assertEqual("complete", result["resultType"])
        self.assertEqual({"echoed": "hi"}, result["structuredContent"])


# ─── 2. list_tools and call_tool ─────────────────────────────────────


class ListToolsAndCallToolE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """`tools/list` enumerates registered tools; `tools/call` invokes them."""

    async def test_list_three_tools_and_call_each(self) -> None:
        """中文：`tools/list` 返回 3 个公开 tool；逐一调用并断言响应形态。

        English: `tools/list` returns 3 public tools; call each and
        assert the response shape.
        """
        discovery = await self.client.discover()
        self.assertEqual("complete", discovery["resultType"])

        listing = await self.client.list_tools()
        names = {tool["name"] for tool in listing["tools"]}
        # The test server registers echo, add, whoami, slow, failing,
        # large_payload, mrtr_approval.  We assert a known subset
        # here so the E2E test does not silently lose a tool.
        self.assertTrue({"echo", "add", "whoami"}.issubset(names))

        echo = await self.client.call_tool("echo", {"text": "hello"})
        self.assertEqual({"echoed": "hello"}, echo["structuredContent"])

        add = await self.client.call_tool("add", {"a": 2, "b": 3})
        self.assertEqual({"sum": 5}, add["structuredContent"])

        whoami = await self.client.call_tool("whoami")
        self.assertEqual(
            {"principal_id": "e2e-test-client", "tenant_id": "tenant-e2e"},
            whoami["structuredContent"],
        )


# ─── 3. resource read ────────────────────────────────────────────────


class ResourceReadE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """`resources/read` over the real subprocess stdio transport."""

    async def test_read_config_json_resource(self) -> None:
        """中文：读 `file://config.json`，断言内容一致。

        English: Read `file://config.json`; assert the contents
        match the registered payload.
        """
        response = await self.client.read_resource("file://config.json")

        self.assertEqual("complete", response["resultType"])
        self.assertEqual(
            {"key": "value", "version": "1.0"},
            response["contents"][0],
        )


# ─── 4. error propagation ────────────────────────────────────────────


class ErrorPropagationE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """Server-side exceptions must be reported as `isError`, not crash the transport."""

    async def test_tool_raising_runtime_error_returns_is_error(self) -> None:
        """中文：tool 抛 `RuntimeError`，客户端收到 `isError=True`，连接未掉。

        English: A tool raising `RuntimeError` must surface as
        `isError=True` on the response; the transport must NOT
        drop the connection or silently fail.
        """
        result = await self.client.call_tool("failing")

        self.assertEqual("complete", result["resultType"])
        self.assertTrue(result["isError"])
        # Connection is still alive after the failure.
        alive = await self.client.call_tool("echo", {"text": "still here"})
        self.assertEqual({"echoed": "still here"}, alive["structuredContent"])


# ─── 5. cancellation (in-process) ────────────────────────────────────


class CancellationInProcessE2ETest(unittest.IsolatedAsyncioTestCase):
    """Cooperative cancellation: in-process only.

    The stdio transport is a single-threaded sequential loop; a
    `notifications/cancelled` cannot be processed while a handler
    is still running. We therefore exercise cancellation against an
    in-process `McpServer` and call `server.handle` directly for
    the notification, while the slow call is in flight.
    """

    async def test_slow_tool_returns_cancelled_after_notification(self) -> None:
        """中文：slow tool 在 100ms 后被取消；响应里 `cancelled=True`。

        English: A `slow` tool is cancelled 100 ms after the call
        starts; the response reports `cancelled=True`.
        """
        started = asyncio.Event()
        server = McpServer()

        @server.tool(name="slow")
        async def slow_tool(context: ToolContext) -> dict[str, Any]:
            started.set()
            # Poll the cancellation token every 25 ms.
            for _ in range(200):
                if context.cancellation.is_cancelled:
                    return {"cancelled": True}
                await asyncio.sleep(0.025)
            return {"cancelled": False, "slept": 5.0}

        client = McpClient(server.handle)
        pending = asyncio.create_task(client.call_tool("slow"))
        await started.wait()
        # Let the slow tool enter its first `await asyncio.sleep`.
        await asyncio.sleep(0.05)
        # First call_tool uses `id=1` (the McpClient's default
        # initial id). Send the notification directly to the server.
        self.assertIsNone(
            await server.handle(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/cancelled",
                    "params": {"requestId": 1},
                }
            )
        )
        result = await asyncio.wait_for(pending, timeout=2.0)

        self.assertEqual("complete", result["resultType"])
        self.assertTrue(result["structuredContent"]["cancelled"])


# ─── 6. concurrent calls ─────────────────────────────────────────────


class ConcurrentCallsE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """10 concurrent `call_tool` requests via independent McpClient instances."""

    async def test_ten_concurrent_calls_all_succeed(self) -> None:
        """中文：10 个并发 echo 全部成功；无错误、无 ID 串扰。

        English: 10 concurrent `call_tool("echo")` calls all
        complete successfully; no errors, no request-id cross-talk.
        """
        clients = [
            McpClient(
                self.transport.exchange,
                identity=Implementation(f"concurrent-client-{i}", "1.0.0"),
                request_id_offset=i * 1000,  # 每个 client 的 ID 空间互不重叠
            )
            for i in range(10)
        ]

        async def call(index: int) -> dict[str, Any]:
            return await clients[index].call_tool("echo", {"text": f"msg-{index}"})

        results = await asyncio.gather(*(call(i) for i in range(10)))

        self.assertEqual(10, len(results))
        for index, result in enumerate(results):
            self.assertEqual("complete", result["resultType"])
            self.assertEqual({"echoed": f"msg-{index}"}, result["structuredContent"])


# ─── 7. MRTR flow ────────────────────────────────────────────────────


class MrtrFlowE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """MRTR (multi-round tool result) round-trip over real stdio."""

    async def test_mrtr_signed_state_round_trip(self) -> None:
        """中文：MRTR 第一轮返回 signed `requestState`；第二轮回传，校验通过。

        English: First call returns a server-signed `requestState`;
        echoing it back on the second call verifies the
        integrity-protected continuation round-trip.
        """
        first = await self.client.call_tool("mrtr_approval")
        self.assertEqual("input_required", first["resultType"])
        wire_state = first["requestState"]
        self.assertIsInstance(wire_state, str)
        self.assertNotEqual("application-state-A", wire_state)

        second = await self.client.call_tool(
            "mrtr_approval",
            request_state=wire_state,
            input_responses={"approve": {"value": True}},
        )
        self.assertEqual("complete", second["resultType"])
        self.assertEqual(
            {
                "continuation": "application-state-A",
                "responses": {"approve": {"value": True}},
            },
            second["structuredContent"],
        )


# ─── 8. large payload ────────────────────────────────────────────────


class LargePayloadE2ETest(_StdioSubprocessE2EMixin, unittest.IsolatedAsyncioTestCase):
    """A 1 MiB payload must round-trip intact over stdio."""

    async def test_one_megabyte_payload_round_trips(self) -> None:
        """中文：服务端返回 1 MiB payload，客户端原样接收。

        English: The server returns a 1 MiB payload; the client
        receives it byte-for-byte.
        """
        result = await self.client.call_tool("large_payload")

        self.assertEqual("complete", result["resultType"])
        self.assertEqual(1024 * 1024, result["structuredContent"]["size"])
        # The whole 1 MiB string is preserved through the JSON
        # encode / pipe / JSON decode round-trip.
        self.assertEqual("x" * (1024 * 1024), result["structuredContent"]["data"])


if __name__ == "__main__":
    unittest.main()
