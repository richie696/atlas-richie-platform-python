"""MCP Streamable HTTP SSE response consumer.

Consumes a `text/event-stream` response and yields MCP JSON-RPC messages
as they arrive. The state of one consumer progresses through a small finite
state machine; transitions are explicit so the consumer can be reasoned
about, tested, and shut down deterministically.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Mapping

from atlas_richie.http import (
    DEFAULT_EVENT_NAME,
    SseEvent,
    SseEventParser,
)
from atlas_richie.http.models import AsyncHttpStreamResponse
from atlas_richie.mcp import CancellationToken, ProgressUpdate


SSE_PROGRESS_METHOD = "notifications/progress"


class SseConsumerState(StrEnum):
    """One consumer progresses through exactly these states.

    Legal transitions:
        INIT       -> READING on first event
        READING    -> COMPLETED on terminal response
        READING    -> FAILED on parse or transport error
        READING    -> CANCELLED when `CancellationToken` fires
        COMPLETED  -> (terminal)
        FAILED     -> (terminal)
        CANCELLED  -> (terminal)
    """

    INIT = "init"
    READING = "reading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SseMcpMessage:
    """One MCP JSON-RPC envelope observed on an SSE stream.

    Attributes:
        kind: The shape of the payload — `response` (terminal reply),
            `request` (server-initiated call), `notification` (event with
            no `id`), `error` (JSON-RPC error), or `cancelled` (the
            consumer observed a cancellation locally).
        payload: The decoded JSON object the consumer produced.
        event_id: The SSE `id:` field, when the server sent one.
        event_name: The SSE `event:` field, when the server sent a
            non-default name.
    """

    kind: Literal["response", "request", "notification", "error", "cancelled"]
    payload: Mapping[str, Any]
    event_id: str | None = None
    event_name: str = DEFAULT_EVENT_NAME


ProgressCallback = Callable[[ProgressUpdate], None]
"""Observer hook for `notifications/progress`; must not raise into the consumer."""


class SseConsumerError(RuntimeError):
    """Raised when the consumer transitions to FAILED."""


def _require_progress_token(token: object) -> str | int:
    if isinstance(token, (str, int)):
        return token
    raise SseConsumerError("progressToken must be a string or integer")


def _require_progress_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SseConsumerError(f"{field} must be a number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise SseConsumerError(f"{field} must be finite")
    return number


def _parse_progress(params: Mapping[str, Any]) -> ProgressUpdate:
    token = _require_progress_token(params["progressToken"])
    progress = _require_progress_number(params["progress"], field="progress")
    total_raw = params.get("total")
    message_raw = params.get("message")
    total = _require_progress_number(total_raw, field="total") if total_raw is not None else None
    message = message_raw if isinstance(message_raw, str) else None
    return ProgressUpdate(progress=progress, total=total, message=message)


def _parse_envelope(data: str) -> Mapping[str, Any]:
    try:
        decoded = json.loads(data)
    except json.JSONDecodeError as exc:
        raise SseConsumerError(f"SSE data is not valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, Mapping):
        raise SseConsumerError("SSE JSON-RPC envelope must be an object")
    return decoded


def _classify(envelope: Mapping[str, Any], *, event: SseEvent) -> SseMcpMessage:
    if "error" in envelope:
        return SseMcpMessage(
            kind="error", payload=envelope, event_id=event.event_id, event_name=event.event
        )
    if "method" in envelope and "id" in envelope:
        return SseMcpMessage(
            kind="request", payload=envelope, event_id=event.event_id, event_name=event.event
        )
    if "method" in envelope:
        return SseMcpMessage(
            kind="notification",
            payload=envelope,
            event_id=event.event_id,
            event_name=event.event,
        )
    if "id" in envelope:
        return SseMcpMessage(
            kind="response", payload=envelope, event_id=event.event_id, event_name=event.event
        )
    raise SseConsumerError("SSE JSON-RPC envelope has no recognizable discriminator")


def _envelope_kind(envelope: Mapping[str, Any]) -> str:
    if "error" in envelope:
        return "error"
    if "method" in envelope and "id" in envelope:
        return "request"
    if "method" in envelope:
        return "notification"
    if "id" in envelope:
        return "response"
    return "unknown"


def _handle_event(
    event: SseEvent,
    *,
    on_progress: ProgressCallback | None,
    seen_progress_tokens: set[str | int],
) -> SseMcpMessage | None:
    """Return a terminal or progress-bearing message, or `None` to keep reading.

    `notifications/progress` invokes `on_progress` (deduped by
    `progressToken`); if no observer is registered the notification is
    yielded so callers without an observer still see it. Any other
    envelope is classified and returned.
    """
    if event.data is None:
        return None
    envelope = _parse_envelope(event.data)
    method = envelope.get("method")
    if isinstance(method, str) and method == SSE_PROGRESS_METHOD:
        params = envelope.get("params")
        if not isinstance(params, Mapping):
            raise SseConsumerError("notifications/progress requires a params object")
        token = _require_progress_token(params["progressToken"])
        if token in seen_progress_tokens:
            # Duplicate progress events are always discarded, even when no
            # observer is registered, so consumers without an observer do
            # not see the same progress twice if a server retries.
            return None
        seen_progress_tokens.add(token)
        if on_progress is not None:
            try:
                on_progress(_parse_progress(params))
            except Exception:  # noqa: BLE001 - observers must not break the consumer
                pass
            return None
        return _classify(envelope, event=event)
    return _classify(envelope, event=event)


async def consume_sse_response(
    stream: AsyncHttpStreamResponse,
    *,
    on_progress: ProgressCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> AsyncIterator[SseMcpMessage]:
    """Yield MCP JSON-RPC messages as SSE events arrive.

    The consumer yields zero or more `SseMcpMessage` values and terminates
    when the first terminal message (response, error, or cancelled) is
    observed. Mid-stream `notifications/progress` events invoke
    `on_progress` exactly once per unique `progressToken`; any exception
    raised by `on_progress` is swallowed so the consumer cannot be killed
    by a faulty subscriber.

    Setting `cancellation_token.is_cancelled` mid-stream transitions the
    consumer to CANCELLED and yields one synthetic message of kind
    `cancelled`; the caller is responsible for the actual cancellation
    notification to the server (typically `DELETE` or a JSON-RPC
    `notifications/cancelled`).
    """
    state = SseConsumerState.INIT
    parser = SseEventParser()
    seen_progress_tokens: set[str | int] = set()
    line_buffer = _LineBuffer()
    try:
        async for chunk in stream.aiter_bytes():
            if state is SseConsumerState.CANCELLED:
                break
            for line in line_buffer.feed(chunk):
                if state is SseConsumerState.CANCELLED:
                    break
                sse_event = parser.feed(line)
                if sse_event is None:
                    continue
                if state is SseConsumerState.INIT:
                    state = SseConsumerState.READING
                message = _handle_event(
                    sse_event,
                    on_progress=on_progress,
                    seen_progress_tokens=seen_progress_tokens,
                )
                if message is None:
                    continue
                yield message
                if message.kind == "cancelled":
                    state = SseConsumerState.CANCELLED
                    return
                if message.kind in ("response", "error"):
                    state = SseConsumerState.COMPLETED
                    return
            if cancellation_token is not None and cancellation_token.is_cancelled:
                state = SseConsumerState.CANCELLED
                yield SseMcpMessage(kind="cancelled", payload={"reason": "caller-cancelled"})
                return
        trailing = parser.flush()
        for line in line_buffer.drain():
            if state is SseConsumerState.CANCELLED:
                break
            trailing = parser.feed(line)
            if trailing is None:
                continue
        trailing = parser.flush()
        if trailing is not None and state is not SseConsumerState.CANCELLED:
            if state is SseConsumerState.INIT:
                state = SseConsumerState.READING
            message = _handle_event(
                trailing,
                on_progress=on_progress,
                seen_progress_tokens=seen_progress_tokens,
            )
            if message is not None:
                yield message
                if message.kind in ("response", "error"):
                    state = SseConsumerState.COMPLETED
        if state is SseConsumerState.INIT:
            state = SseConsumerState.COMPLETED
    except SseConsumerError:
        state = SseConsumerState.FAILED
        raise


__all__ = [
    "SSE_PROGRESS_METHOD",
    "ProgressCallback",
    "SseConsumerError",
    "SseConsumerState",
    "SseMcpMessage",
    "consume_sse_response",
]


class _LineBuffer:
    """Decode UTF-8 bytes into complete lines, buffering the trailing partial line.

    A single SSE field value may straddle two HTTP chunks, so the consumer
    must accumulate bytes until it sees a newline before handing a line to
    `SseEventParser`.
    """

    def __init__(self) -> None:
        self._carry: str = ""

    def feed(self, chunk: bytes) -> list[str]:
        if not chunk:
            return []
        text = self._carry + chunk.decode("utf-8", errors="replace")
        if text.endswith("\n"):
            lines = text.splitlines()
            self._carry = ""
            return lines
        split = text.rsplit("\n", 1)
        if len(split) == 1:
            self._carry = split[0]
            return []
        complete, partial = split
        self._carry = partial
        return complete.splitlines()

    def drain(self) -> list[str]:
        """Return any buffered partial line as the final line, then clear."""
        if not self._carry:
            return []
        line = self._carry
        self._carry = ""
        return [line]
