"""Minimal MCP test server for `test_e2e_mcp.py` E2E suite.

中文
----
子进程式 MCP test server:为 E2E 测试提供一组代表性的 tools /
resource / MRTR state。运行方式:

    python components/mcp/tests/_e2e_test_server.py

服务从 `sys.stdin.buffer` 读 newline-delimited JSON-RPC 帧,
把响应写回 `sys.stdout.buffer`,直到 stdin EOF。**严禁**向
stdout 写诊断信息(那会污染对端的 framing)。

English
--------
Subprocess-mode MCP test server: provides a representative set of
tools, a resource, and MRTR state for the E2E tests. Run with:

    python components/mcp/tests/_e2e_test_server.py

Reads newline-delimited JSON-RPC frames from `sys.stdin.buffer` and
writes responses to `sys.stdout.buffer` until stdin EOF. Diagnostics
**must not** be written to stdout (that would corrupt the peer's
framing).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from atlas_richie.mcp import (
    InputRequired,
    McpServer,
    MrtRequestStateCodec,
    MrtStateBinding,
    ToolContext,
)
from atlas_richie.mcp.transport.stdio import serve_stdio


# MRTR state binding — the test client does not need to know the
# secret; the server's `MrtStateBinding` signs / verifies the
# `requestState` token transparently. The secret is fixed so the
# signing is deterministic across runs.
_MRTR_SECRET = b"e2e-mrtr-secret-fixed-32-bytes-ok!"
_MRTR_RESOURCE = "https://e2e.test/mcp"
_MRTR_BINDING = MrtStateBinding(
    MrtRequestStateCodec(_MRTR_SECRET),
    resource=_MRTR_RESOURCE,
    principal_fingerprint=lambda ctx: f"principal:{ctx.principal_id or 'anonymous'}",
)


def _context_factory(meta: dict[str, Any]) -> ToolContext:
    """Build a per-call `ToolContext` carrying a stable principal id.

    The principal id is sourced from the client's `clientInfo` so
    MRTR-bound tools see a stable identity across rounds.
    """

    client_info = meta.get("io.modelcontextprotocol/clientInfo") or {}
    principal_id = client_info.get("name") if isinstance(client_info, dict) else None
    return ToolContext(
        principal_id=str(principal_id) if principal_id else "anonymous",
        tenant_id="tenant-e2e",
    )


server = McpServer(
    identity=None,
    instructions="atlas-richie-mcp e2e test server",
    context_factory=_context_factory,
    mrtr_state=_MRTR_BINDING,
)


@server.tool(description="Echo the text back unchanged")
def echo(_ctx: ToolContext, text: str) -> dict[str, str]:
    return {"echoed": text}


@server.tool(description="Add two integers")
def add(_ctx: ToolContext, a: int, b: int) -> dict[str, int]:
    return {"sum": a + b}


@server.tool(description="Return the principal id and tenant id from the request context")
def whoami(ctx: ToolContext) -> dict[str, str | None]:
    return {"principal_id": ctx.principal_id, "tenant_id": ctx.tenant_id}


@server.tool(name="slow", description="Sleep for N seconds, polling for cancellation")
async def slow(ctx: ToolContext, seconds: float) -> dict[str, Any]:
    """Cooperative-cancellation slow tool.

    Polls `ctx.cancellation.is_cancelled` every 50ms. Returns early
    with `cancelled=True` if cancellation is observed, or with
    `cancelled=False` once the full duration elapses.
    """

    deadline = asyncio.get_event_loop().time() + max(0.0, seconds)
    elapsed = 0.0
    step = 0.05
    while elapsed < deadline:
        if ctx.cancellation.is_cancelled:
            return {"cancelled": True, "slept_so_far": elapsed}
        await asyncio.sleep(step)
        elapsed += step
    return {"cancelled": False, "slept": seconds}


@server.tool(name="failing", description="Raise a runtime error to exercise error propagation")
def failing(_ctx: ToolContext) -> str:
    raise RuntimeError("intentional failure for E2E test")


@server.tool(name="large_payload", description="Return a 1 MiB JSON payload")
def large_payload(_ctx: ToolContext) -> dict[str, Any]:
    payload = "x" * (1024 * 1024)
    return {"size": len(payload), "data": payload}


@server.tool(name="mrtr_approval", description="Two-round MRTR flow tool")
def mrtr_approval(ctx: ToolContext) -> InputRequired | dict[str, Any]:
    if ctx.request_state is None:
        return InputRequired({"approve": {"type": "boolean"}}, "application-state-A")
    return {
        "continuation": ctx.request_state,
        "responses": dict(ctx.input_responses),
    }


@server.resource(uri="file://config.json", name="config", mime_type="application/json")
def config_resource(_ctx: ToolContext) -> dict[str, str]:
    return {"key": "value", "version": "1.0"}


if __name__ == "__main__":
    asyncio.run(serve_stdio(server, sys.stdin.buffer, sys.stdout.buffer))
