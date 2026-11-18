"""Redis Streams bus: publish, consumer groups, ack, backlog and dead-letter routing.

Synchronous and explicit — the Java module's Reactor pipeline, monitoring
endpoints, tracing wrappers and control bus are out of scope. DLQ key names and
routing strategies match Java's `DeadLetterQueueUtil` exactly.

Wire format: one stream entry per message with fields `body` (JSON), `type`,
and optional `business_id` / `priority`.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any

from .model import (
    BacklogInfo,
    DeadLetterMessage,
    DeadLetterStrategy,
    EventContext,
    PublishFailureReason,
    PublishResult,
    StreamMessage,
)

_log = logging.getLogger(__name__)

DEFAULT_MAX_LEN = 3000


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)


def dead_letter_streams(
    strategy: DeadLetterStrategy, message_type: str, source_stream: str
) -> list[str]:
    """DLQ keys per strategy, matching the Java naming convention."""
    simple_type = message_type.rsplit(".", 1)[-1]
    if strategy is DeadLetterStrategy.GLOBAL:
        return ["dlq:global"]
    if strategy is DeadLetterStrategy.BY_MESSAGE_TYPE:
        return [f"dlq:type:{simple_type}"]
    if strategy is DeadLetterStrategy.BY_SOURCE_STREAM:
        return [f"dlq:stream:{source_stream}"]
    return ["dlq:global", f"dlq:type:{simple_type}", f"dlq:stream:{source_stream}"]


class RedisStreamBus:
    def __init__(
        self,
        client,
        *,
        default_max_len: int | None = DEFAULT_MAX_LEN,
        approximate_trimming: bool = True,
    ) -> None:
        self._client = client
        self._default_max_len = default_max_len
        self._approximate_trimming = approximate_trimming

    @property
    def client(self):
        return self._client

    def publish(
        self,
        stream: str,
        body: Any,
        *,
        business_id: str | None = None,
        priority: str | None = None,
        max_len: int | None = None,
    ) -> PublishResult:
        try:
            payload = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            return PublishResult.failed(PublishFailureReason.SERIALIZATION_ERROR, str(error))
        fields = {"body": payload, "type": type(body).__name__}
        if business_id is not None:
            fields["business_id"] = business_id
        if priority is not None:
            fields["priority"] = priority
        limit = max_len if max_len is not None else self._default_max_len
        try:
            if limit is not None:
                record_id = self._client.xadd(
                    stream, fields, maxlen=limit, approximate=self._approximate_trimming
                )
            else:
                record_id = self._client.xadd(stream, fields)
        except Exception as error:  # noqa: BLE001 — surfaced as a result, not a raise
            _log.error("stream publish failed; stream=%s exceptionType=%s", stream, type(error).__name__)
            return PublishResult.failed(PublishFailureReason.REDIS_ERROR, str(error))
        return PublishResult.ok(_text(record_id))

    def ensure_group(self, stream: str, group: str, *, start_id: str = "$", mkstream: bool = True) -> bool:
        """Create the consumer group; True when created, False when it already exists."""
        try:
            self._client.xgroup_create(stream, group, id=start_id, mkstream=mkstream)
            return True
        except Exception as error:  # noqa: BLE001 — BUSYGROUP means it already exists
            if "BUSYGROUP" in str(error):
                return False
            raise

    def read(
        self,
        stream: str,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_millis: int | None = None,
        last_id: str = ">",
    ) -> list[StreamMessage]:
        """`last_id=">"` reads new messages; `"0"` re-reads this consumer's pending ones."""
        response = self._client.xreadgroup(
            group, consumer, {stream: last_id}, count=count, block=block_millis
        )
        if not response:
            return []
        messages: list[StreamMessage] = []
        for stream_name, entries in response:
            name = _text(stream_name)
            for record_id, fields in entries:
                decoded = {_text(k): _text(v) for k, v in fields.items()}
                messages.append(self._to_message(name, _text(record_id), decoded))
        return messages

    @staticmethod
    def _to_message(stream: str, record_id: str, fields: dict[str, str]) -> StreamMessage:
        raw = fields.get("body")
        body: Any = raw
        if raw is not None:
            try:
                body = json.loads(raw)
            except (TypeError, ValueError):
                body = raw
        return StreamMessage(
            stream=stream,
            id=record_id,
            body=body,
            message_type=fields.get("type"),
            business_id=fields.get("business_id"),
            priority=fields.get("priority"),
        )

    def ack(self, stream: str, group: str, *record_ids: str) -> int:
        if not record_ids:
            return 0
        return int(self._client.xack(stream, group, *record_ids))

    def delivery_counts(self, stream: str, group: str, consumer: str) -> dict[str, int]:
        """Pending record id -> times delivered, used to decide retry exhaustion."""
        entries = self._client.xpending_range(stream, group, min="-", max="+", count=1000, consumername=consumer)
        counts: dict[str, int] = {}
        for entry in entries or []:
            if isinstance(entry, dict):
                counts[_text(entry.get("message_id"))] = int(entry.get("times_delivered", 1))
            else:
                counts[_text(entry[0])] = int(entry[3])
        return counts

    def backlog(self, stream: str, group: str | None = None) -> BacklogInfo:
        length = int(self._client.xlen(stream))
        if group is None:
            return BacklogInfo(stream=stream, length=length)
        summary = self._client.xpending(stream, group)
        if isinstance(summary, dict):
            pending = int(summary.get("pending", 0))
            consumers = tuple(_text(c.get("name")) for c in summary.get("consumers", []) or [])
        else:
            pending = int(summary[0]) if summary else 0
            consumers = tuple(_text(c[0]) for c in (summary[3] or [])) if len(summary) > 3 else ()
        return BacklogInfo(stream=stream, length=length, group=group, pending=pending, consumers=consumers)

    def trim(self, stream: str, max_len: int, *, approximate: bool | None = None) -> int:
        """Cap an existing stream, returning how many entries were removed.

        Publishing trims only on XADD, so a stream that stops receiving messages
        keeps its backlog forever. This is the standalone cap for that case.
        A missing stream is a no-op (0), matching Java's hasKey guard.
        """
        if max_len < 0:
            raise ValueError("max_len must be >= 0")
        use_approximate = (
            self._approximate_trimming if approximate is None else approximate
        )
        try:
            return int(
                self._client.xtrim(stream, maxlen=max_len, approximate=use_approximate)
            )
        except Exception as error:  # noqa: BLE001 — a missing stream is not an error
            if "no such key" in str(error).lower():
                return 0
            raise

    def send_to_dead_letter(
        self,
        message: StreamMessage,
        error: BaseException,
        context: EventContext,
        source_consumer: str,
        *,
        strategy: DeadLetterStrategy = DeadLetterStrategy.GLOBAL,
        retry_count: int | None = None,
    ) -> list[str]:
        """Route a failed message to the DLQ stream(s); failures are logged, not raised."""
        dead_letter = DeadLetterMessage(
            original_message=message.body,
            original_message_type=message.message_type or type(message.body).__name__,
            original_stream_key=context.stream_key,
            original_group=context.group,
            original_record_id=context.record_id,
            error_message=str(error),
            error_type=type(error).__name__,
            stack_trace="".join(traceback.format_exception(type(error), error, error.__traceback__)),
            timestamp=int(time.time() * 1000),
            source_consumer=source_consumer,
            retry_count=retry_count,
            business_id=message.business_id,
            priority=message.priority,
        )
        payload = {
            "original_message": dead_letter.original_message,
            "original_message_type": dead_letter.original_message_type,
            "original_stream_key": dead_letter.original_stream_key,
            "original_group": dead_letter.original_group,
            "original_record_id": dead_letter.original_record_id,
            "error_message": dead_letter.error_message,
            "error_type": dead_letter.error_type,
            "stack_trace": dead_letter.stack_trace,
            "timestamp": dead_letter.timestamp,
            "source_consumer": dead_letter.source_consumer,
            "retry_count": dead_letter.retry_count,
            "business_id": dead_letter.business_id,
            "priority": dead_letter.priority,
        }
        record_ids: list[str] = []
        for target in dead_letter_streams(strategy, dead_letter.original_message_type, context.stream_key):
            result = self.publish(target, payload)
            if result.success and result.record_id is not None:
                record_ids.append(result.record_id)
            else:
                _log.error("dead letter publish failed; target=%s reason=%s", target, result.reason)
        return record_ids


__all__ = ["DEFAULT_MAX_LEN", "RedisStreamBus", "dead_letter_streams"]
