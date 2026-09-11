"""Unit tests for the MCP SSE consumer."""

from __future__ import annotations

import unittest
from collections.abc import AsyncIterator, Callable
from typing import Any

from atlas_richie.http.models import AsyncHttpStreamResponse
from atlas_richie.mcp import ProgressUpdate
from atlas_richie.mcp_http import (
    SseConsumerError,
    SseConsumerState,
    SseMcpMessage,
    consume_sse_response,
)


def _stream(chunks: list[bytes], *, status_code: int = 200) -> AsyncHttpStreamResponse:
    async def _iter() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk

    async def _close() -> None:
        return None

    return AsyncHttpStreamResponse(
        status_code=status_code,
        headers={"content-type": "text/event-stream"},
        method="POST",
        url="https://peer.example/mcp",
        iter_bytes=_iter,
        close=_close,
    )


async def _collect(
    stream: AsyncHttpStreamResponse,
    *,
    on_progress: Callable[[ProgressUpdate], None] | None = None,
    cancellation_token: Any | None = None,
) -> list[SseMcpMessage]:
    messages: list[SseMcpMessage] = []
    async for message in consume_sse_response(
        stream,
        on_progress=on_progress,
        cancellation_token=cancellation_token,
    ):
        messages.append(message)
    return messages


class SseConsumerStateMachineTest(unittest.IsolatedAsyncioTestCase):
    async def test_yields_terminal_response_after_progress(self) -> None:
        progress: list[ProgressUpdate] = []
        sse = (
            b"event: message\n"
            b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.5,"total":1.0}}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        )
        messages = await _collect(_stream([sse]), on_progress=progress.append)
        self.assertEqual(1, len(messages))
        self.assertEqual("response", messages[0].kind)
        self.assertEqual({"ok": True}, dict(messages[0].payload["result"]))
        self.assertEqual(1, len(progress))
        self.assertEqual(0.5, progress[0].progress)
        self.assertEqual(1.0, progress[0].total)

    async def test_yields_error_frame(self) -> None:
        sse = b'data: {"jsonrpc":"2.0","id":1,"error":{"code":-32603,"message":"boom"}}\n\n'
        messages = await _collect(_stream([sse]))
        self.assertEqual(1, len(messages))
        self.assertEqual("error", messages[0].kind)
        self.assertEqual(-32603, messages[0].payload["error"]["code"])

    async def test_progress_events_without_observer_are_yielded(self) -> None:
        sse = b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.25}}\n\n'
        messages = await _collect(_stream([sse]))
        self.assertEqual(1, len(messages))
        self.assertEqual("notification", messages[0].kind)
        self.assertEqual("notifications/progress", messages[0].payload["method"])

    async def test_progress_token_is_deduped(self) -> None:
        progress: list[ProgressUpdate] = []
        sse = (
            b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.1}}\n\n'
            b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.5}}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        )
        messages = await _collect(_stream([sse]), on_progress=progress.append)
        self.assertEqual(1, len(progress))
        self.assertEqual(0.1, progress[0].progress)
        self.assertEqual(1, len(messages))
        self.assertEqual("response", messages[0].kind)

    async def test_observer_exception_is_isolated(self) -> None:
        def bad_callback(_update: ProgressUpdate) -> None:
            raise RuntimeError("subscriber blew up")

        sse = (
            b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"t1","progress":0.1}}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        )
        messages = await _collect(_stream([sse]), on_progress=bad_callback)
        self.assertEqual(1, len(messages))
        self.assertEqual("response", messages[0].kind)

    async def test_invalid_json_raises_consumer_error(self) -> None:
        sse = b"data: not-json\n\n"
        with self.assertRaises(SseConsumerError):
            await _collect(_stream([sse]))

    async def test_unknown_envelope_shape_raises_consumer_error(self) -> None:
        sse = b"data: {}\n\n"
        with self.assertRaises(SseConsumerError):
            await _collect(_stream([sse]))

    async def test_cancellation_token_yields_synthetic_message(self) -> None:
        from atlas_richie.mcp import CancellationToken

        token = CancellationToken()
        sse = b"event: message\n"
        stream = _stream([sse])

        async def _run() -> list[SseMcpMessage]:
            return await _collect(stream, cancellation_token=token)

        # Cancel before the consumer iterates the first chunk; the consumer
        # notices between iterations and yields the synthetic message.
        token.cancel()
        messages = await _run()
        self.assertEqual(1, len(messages))
        self.assertEqual("cancelled", messages[0].kind)

    async def test_stream_without_data_yields_nothing(self) -> None:
        messages = await _collect(_stream([b""]))
        self.assertEqual([], messages)

    async def test_chunked_input_is_parsed_across_boundaries(self) -> None:
        chunks = [
            b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":1,\"res",
            b'ult":{"x":1}}\n\n',
        ]
        messages = await _collect(_stream(chunks))
        self.assertEqual(1, len(messages))
        self.assertEqual("response", messages[0].kind)
        self.assertEqual(1, messages[0].payload["result"]["x"])

    def test_state_machine_terminal_values(self) -> None:
        self.assertEqual(
            {"init", "reading", "completed", "failed", "cancelled"},
            {state.value for state in SseConsumerState},
        )
