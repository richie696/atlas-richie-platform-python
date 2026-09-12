"""MCP HTTP exchange mapped onto the owned HTTP abstraction.

The exchange now also consumes Streamable HTTP SSE responses. When the
server returns `text/event-stream`, the exchange opens a stream, routes
`notifications/progress` through an optional observer, and returns one
final JSON-RPC response to its caller. The non-SSE path is unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from atlas_richie.http import HttpRequest, HttpResponse
from atlas_richie.http.models import AsyncHttpStreamResponse
from atlas_richie.mcp import CancellationToken, McpError
from atlas_richie.mcp.protocol import MODERN_PROTOCOL_VERSION
from atlas_richie.oauth import DpopProofFactory

from .sse_consumer import (
    ProgressCallback,
    SseConsumerError,
    consume_sse_response,
)


SSE_CONTENT_TYPE = "text/event-stream"
JSON_CONTENT_TYPE = "application/json"


class AsyncHttpExecutor(Protocol):
    """An HTTP executor that can both buffer and stream.

    The MCP exchange inspects the response `Content-Type` and routes
    SSE responses through the streaming path. Executors that cannot
    stream must implement `open_stream` by raising `NotImplementedError`
    so the exchange fails fast rather than silently dropping events.
    """

    def execute(self, request: HttpRequest) -> Awaitable[HttpResponse]: ...

    async def open_stream(self, request: HttpRequest) -> AsyncHttpStreamResponse: ...


class AuthorizationProvider(Protocol):
    """Obtains a fresh target-bound HTTP authorization value for one MCP request."""

    def authorization_for(self) -> str: ...


class McpHttpExchange:
    """Callable exchange for `McpClient`; owns MCP headers, JSON mapping, and SSE consumption."""

    def __init__(
        self,
        endpoint: str,
        http: AsyncHttpExecutor,
        *,
        authorization: str | None = None,
        authorization_provider: AuthorizationProvider | None = None,
        dpop_proof_factory: DpopProofFactory | None = None,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("MCP HTTP endpoint must use HTTPS")
        if authorization is not None and authorization_provider is not None:
            raise ValueError("MCP exchange accepts either authorization or authorization_provider")
        if dpop_proof_factory is not None and authorization_provider is None and _dpop_access_token(authorization) is None:
            raise ValueError("DPoP MCP exchange requires a DPoP authorization token")
        self._endpoint = endpoint
        self._http = http
        self._authorization = authorization
        self._authorization_provider = authorization_provider
        self._dpop_proof_factory = dpop_proof_factory

    async def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        on_progress: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Mapping[str, Any]:
        method = payload.get("method")
        if not isinstance(method, str):
            raise McpError(-32600, "MCP request method is required")
        headers: dict[str, str] = {
            "Accept": f"{JSON_CONTENT_TYPE}, {SSE_CONTENT_TYPE}",
            "MCP-Protocol-Version": MODERN_PROTOCOL_VERSION,
            "Mcp-Method": method,
        }
        params = payload.get("params")
        if isinstance(params, Mapping):
            name = params.get("name") or params.get("uri")
            if isinstance(name, str):
                headers["Mcp-Name"] = name
        authorization = self._authorization_value()
        if authorization:
            headers["Authorization"] = authorization
        if self._dpop_proof_factory is not None:
            access_token = _dpop_access_token(authorization)
            if access_token is None:
                raise McpError(-32000, "DPoP MCP authorization provider returned no DPoP token")
            headers["DPoP"] = self._dpop_proof_factory.create(
                method="POST", target_uri=self._endpoint, access_token=access_token
            )
        request = HttpRequest.json("POST", self._endpoint, payload, headers=headers)
        stream = await self._http.open_stream(request)
        content_type = _content_type(stream.headers)
        if content_type == SSE_CONTENT_TYPE:
            if stream.status_code != 200:
                await stream.aclose()
                raise McpError(
                    -32000,
                    "MCP HTTP transport rejected request",
                    {"status": stream.status_code},
                )
            try:
                return await self._consume_sse(
                    stream, on_progress=on_progress, cancellation_token=cancellation_token
                )
            except SseConsumerError as exc:
                raise McpError(
                    -32603,
                    "MCP HTTP SSE stream produced an invalid frame",
                    {"reason": str(exc)},
                ) from exc
        # Non-SSE: drain the body and return the JSON-RPC response.
        body = await _drain_stream_body(stream)
        if stream.status_code != 200:
            raise McpError(
                -32000,
                "MCP HTTP transport rejected request",
                {"status": stream.status_code},
            )
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise McpError(
                -32603, "MCP HTTP endpoint returned a non-JSON response", {"reason": exc.msg}
            ) from exc
        if not isinstance(decoded, Mapping):
            raise McpError(-32603, "MCP HTTP endpoint returned a non-object response")
        return decoded

    async def _consume_sse(
        self,
        stream: AsyncHttpStreamResponse,
        *,
        on_progress: ProgressCallback | None,
        cancellation_token: CancellationToken | None,
    ) -> Mapping[str, Any]:
        terminal: Mapping[str, Any] | None = None
        try:
            async for message in consume_sse_response(
                stream, on_progress=on_progress, cancellation_token=cancellation_token
            ):
                if message.kind == "response":
                    terminal = message.payload
                    break
                if message.kind == "error":
                    raise McpError(
                        -32000,
                        "MCP HTTP SSE stream reported a JSON-RPC error",
                        {"error": dict(message.payload)},
                    )
                if message.kind == "cancelled":
                    raise McpError(-32000, "MCP HTTP exchange was cancelled by the caller")
        finally:
            await stream.aclose()
        if terminal is None:
            raise McpError(
                -32000,
                "MCP HTTP SSE stream ended without a terminal response",
                {"status": stream.status_code},
            )
        return terminal

    def _authorization_value(self) -> str | None:
        if self._authorization_provider is None:
            return self._authorization
        value = self._authorization_provider.authorization_for()
        if not isinstance(value, str) or not value.strip():
            raise McpError(-32000, "MCP authorization provider returned no authorization value")
        return value


def _dpop_access_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, value = authorization.partition(" ")
    return value if separator and scheme.casefold() == "dpop" and value else None


def _content_type(headers: Mapping[str, str]) -> str:
    for key, value in headers.items():
        if key.lower() == "content-type":
            return value.split(";", 1)[0].strip().lower()
    return ""


async def _drain_stream_body(stream: AsyncHttpStreamResponse) -> bytes:
    chunks: list[bytes] = []
    async for chunk in stream.aiter_bytes():
        chunks.append(chunk)
    # `aiter_bytes` closes the stream on completion, so no follow-up `aclose` is needed.
    return b"".join(chunks)


__all__ = [
    "AsyncHttpExecutor",
    "AuthorizationProvider",
    "McpHttpExchange",
    "SSE_CONTENT_TYPE",
    "SSE_PROGRESS_METHOD",
]
