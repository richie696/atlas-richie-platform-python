"""ASGI mapping for JSON and Streamable HTTP MCP responses."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from atlas_richie.mcp import Mcp20260728Dialect, McpError, McpServer, ToolContext

from .streaming import (
    DEFAULT_EVENT_BUFFER_CAPACITY,
    ProgressEventReporter,
    SubscriptionManager,
    parse_subscription_spec,
    progress_token,
    subscription_acknowledged,
)

ContextResolver = Callable[[Mapping[str, str]], ToolContext | Awaitable[ToolContext]]
AsgiReceive = Callable[[], Awaitable[Mapping[str, Any]]]
AsgiSend = Callable[[Mapping[str, Any]], Awaitable[None]]

JSON_CONTENT_TYPE = "application/json"
SSE_CONTENT_TYPE = "text/event-stream"
SSE_EVENT_NAME = "message"
SSE_HEADERS = {"content-type": SSE_CONTENT_TYPE, "cache-control": "no-cache"}


class McpAsgiApplication:
    """Mountable ASGI callable; SSE state is explicit and owned by this adapter."""

    def __init__(
        self,
        server: McpServer,
        *,
        context_resolver: ContextResolver | None = None,
        origin_allowed: Callable[[str], bool] | None = None,
        event_buffer_capacity: int = DEFAULT_EVENT_BUFFER_CAPACITY,
    ) -> None:
        self._server = server
        self._context_resolver = context_resolver
        self._origin_allowed = origin_allowed or (lambda _origin: True)
        self._subscriptions = SubscriptionManager(event_buffer_capacity=event_buffer_capacity)
        self._remove_registry_listener = server.add_registry_listener(self._registry_changed)

    @property
    def subscriptions(self) -> SubscriptionManager:
        """Expose deliberate resource-change publication without leaking ASGI objects."""
        return self._subscriptions

    def close(self) -> None:
        """Release all streams when the embedding application's lifecycle ends."""
        self._remove_registry_listener()
        self._subscriptions.close_all()

    async def __call__(self, scope: Mapping[str, Any], receive: AsgiReceive, send: AsgiSend) -> None:
        if scope.get("type") != "http":
            await self._send_json(send, 500, {"error": "MCP ASGI adapter only supports HTTP"})
            return
        if scope.get("method") != "POST":
            await self._send_json(send, 405, {"error": "MCP endpoint only accepts POST"}, {"allow": "POST"})
            return
        headers = {bytes(key).decode("latin-1").casefold(): bytes(value).decode("latin-1") for key, value in scope.get("headers", ())}
        if not _media_type(headers.get("content-type"), JSON_CONTENT_TYPE):
            await self._send_json(send, 415, {"error": "Content-Type must be application/json"})
            return
        if not _accepts_streamable_response(headers.get("accept")):
            await self._send_json(send, 406, {"error": "Accept must include application/json and text/event-stream"})
            return
        origin = headers.get("origin")
        if origin and not self._origin_allowed(origin):
            await self._send_json(send, 403, {"error": "Origin is not allowed"})
            return
        body = await _body(receive)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            await self._send_json(send, 400, _error_envelope(None, -32700, "Parse error"))
            return
        method = payload.get("method") if isinstance(payload, Mapping) else None
        if not isinstance(method, str) or headers.get("mcp-method") != method:
            request_id = payload.get("id") if isinstance(payload, Mapping) else None
            await self._send_json(send, 400, _error_envelope(request_id, -32020, "Mcp-Method header does not match request body"))
            return
        name_field = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}.get(method)
        if name_field is not None:
            params = payload.get("params") if isinstance(payload, Mapping) else None
            expected_name = params.get(name_field) if isinstance(params, Mapping) else None
            if not isinstance(expected_name, str) or headers.get("mcp-name") != expected_name:
                await self._send_json(send, 400, _error_envelope(payload.get("id"), -32020, "Mcp-Name header does not match request body"))
                return
        version = headers.get("mcp-protocol-version")
        if not version:
            request_id = payload.get("id") if isinstance(payload, Mapping) else None
            await self._send_json(send, 400, _error_envelope(request_id, -32020, "MCP-Protocol-Version header is required"))
            return
        try:
            context = await _resolve(self._context_resolver, headers)
        except McpError as error:
            challenge = getattr(error, "challenge", "Bearer")
            await self._send_json(send, 401, {"error": "Unauthorized"}, {"www-authenticate": challenge})
            return

        if method == "subscriptions/listen":
            await self._open_subscription(payload, version, receive, send)
            return
        params = payload.get("params") if isinstance(payload, Mapping) else {}
        token = progress_token(params) if isinstance(params, Mapping) else None
        if token is None:
            response = await self._server.handle(payload, transport_version=version, context=context)
            if response is None:
                await self._send_empty(send, 202)
            else:
                await self._send_json(send, 200, response)
            return
        await self._stream_tool_response(payload, version, context, token, receive, send)

    async def _stream_tool_response(
        self,
        payload: Mapping[str, Any],
        version: str,
        context: ToolContext | None,
        token: str | int,
        receive: AsgiReceive,
        send: AsgiSend,
    ) -> None:
        events: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue()
        reporter = ProgressEventReporter(token, events.put_nowait)
        stream_context = replace(context or ToolContext(), progress=reporter)
        response_task = asyncio.create_task(self._server.handle(payload, transport_version=version, context=stream_context))
        disconnect_task = asyncio.create_task(_wait_for_disconnect(receive))
        event_task = asyncio.create_task(events.get())
        await self._start_sse(send)
        try:
            while not response_task.done():
                done, _ = await asyncio.wait({response_task, disconnect_task, event_task}, return_when=asyncio.FIRST_COMPLETED)
                if disconnect_task in done:
                    stream_context.cancellation.cancel()
                    response_task.cancel()
                    await _consume_cancelled(response_task)
                    return
                if event_task in done:
                    await self._send_sse_event(send, event_task.result())
                    event_task = asyncio.create_task(events.get())
            event_task.cancel()
            await _consume_cancelled(event_task)
            while not events.empty():
                await self._send_sse_event(send, events.get_nowait())
            response = response_task.result()
            if response is not None:
                await self._send_sse_event(send, response)
            await self._end_sse(send)
        finally:
            disconnect_task.cancel()
            event_task.cancel()
            await _consume_cancelled(disconnect_task)
            await _consume_cancelled(event_task)

    async def _open_subscription(self, payload: Mapping[str, Any], version: str, receive: AsgiReceive, send: AsgiSend) -> None:
        try:
            request = Mcp20260728Dialect().parse_request(payload, transport_version=version)
            if request.is_notification or request.request_id is None:
                raise ValueError("subscriptions/listen requires a request id")
            notifications = request.params.get("notifications")
            spec = parse_subscription_spec(notifications)
            identifier = str(request.request_id)
            subscription = self._subscriptions.open(identifier, spec)
        except (McpError, ValueError) as error:
            await self._send_json(send, 400, _error_envelope(payload.get("id"), -32602, str(error)))
            return

        await self._start_sse(send)
        await self._send_sse_event(send, subscription_acknowledged(identifier, notifications))
        events = subscription.events()
        disconnect_task = asyncio.create_task(_wait_for_disconnect(receive))
        event_task = asyncio.create_task(_next(events))
        try:
            while True:
                done, _ = await asyncio.wait({disconnect_task, event_task}, return_when=asyncio.FIRST_COMPLETED)
                if disconnect_task in done:
                    return
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    return
                await self._send_sse_event(send, event)
                event_task = asyncio.create_task(_next(events))
        finally:
            self._subscriptions.close(identifier)
            disconnect_task.cancel()
            event_task.cancel()
            await _consume_cancelled(disconnect_task)
            await _consume_cancelled(event_task)

    def _registry_changed(self, _change: object) -> None:
        self._subscriptions.tools_changed()
        self._subscriptions.prompts_changed()
        self._subscriptions.resources_changed()

    async def _start_sse(self, send: AsgiSend) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": _headers(SSE_HEADERS)})

    async def _send_sse_event(self, send: AsgiSend, payload: Mapping[str, Any]) -> None:
        await send({"type": "http.response.body", "body": _sse_frame(payload), "more_body": True})

    @staticmethod
    async def _end_sse(send: AsgiSend) -> None:
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _send_json(self, send: AsgiSend, status: int, payload: Mapping[str, Any], headers: Mapping[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": _headers({"content-type": JSON_CONTENT_TYPE, **dict(headers or {})})})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _send_empty(send: AsgiSend, status: int) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def _body(receive: AsgiReceive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            return b""
        chunks.append(bytes(message.get("body", b"")))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _resolve(resolver: ContextResolver | None, headers: Mapping[str, str]) -> ToolContext | None:
    if resolver is None:
        return None
    result = resolver(headers)
    return await result if hasattr(result, "__await__") else result


async def _wait_for_disconnect(receive: AsgiReceive) -> None:
    while True:
        if (await receive()).get("type") == "http.disconnect":
            return


async def _next(events: AsyncIterator[Mapping[str, Any]]) -> Mapping[str, Any]:
    return await anext(events)


async def _consume_cancelled(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _media_type(value: str | None, expected: str) -> bool:
    return value is not None and value.split(";", 1)[0].strip().casefold() == expected


def _accepts_streamable_response(value: str | None) -> bool:
    if value is None:
        return False
    accepted = {part.split(";", 1)[0].strip().casefold() for part in value.split(",")}
    return {JSON_CONTENT_TYPE, SSE_CONTENT_TYPE}.issubset(accepted)


def _headers(values: Mapping[str, str]) -> list[tuple[bytes, bytes]]:
    return [(key.encode("latin-1"), value.encode("latin-1")) for key, value in values.items()]


def _sse_frame(payload: Mapping[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {SSE_EVENT_NAME}\ndata: {data}\n\n".encode("utf-8")


def _error_envelope(request_id: object, code: int, message: str) -> Mapping[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
