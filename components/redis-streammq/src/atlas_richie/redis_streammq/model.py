"""Message, context, publish-result and dead-letter models.

Semantics follow the Java `atlas-richie-redis-streammq` beans. This is a
Python-native implementation, not a line-by-line port: the Java module is 8453
lines built on Reactor, and its monitoring/tracing/control-bus plumbing is out of
scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DeadLetterStrategy(StrEnum):
    """Routing strategies; DLQ key names match the Java `DeadLetterQueueUtil`."""

    GLOBAL = "GLOBAL"
    BY_MESSAGE_TYPE = "BY_MESSAGE_TYPE"
    BY_SOURCE_STREAM = "BY_SOURCE_STREAM"
    HYBRID = "HYBRID"


class PublishFailureReason(StrEnum):
    """Java's Reactor-specific reasons are replaced by transport-level ones."""

    REDIS_ERROR = "REDIS_ERROR"
    SERIALIZATION_ERROR = "SERIALIZATION_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ErrorStrategy(StrEnum):
    SKIP = "SKIP"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True, slots=True)
class StreamMessage:
    stream: str
    id: str
    body: Any
    message_type: str | None = None
    business_id: str | None = None
    priority: str | None = None


@dataclass(frozen=True, slots=True)
class EventContext:
    stream_key: str
    group: str
    record_id: str


@dataclass(frozen=True, slots=True)
class PublishResult:
    success: bool
    record_id: str | None = None
    reason: PublishFailureReason | None = None
    error: str | None = None

    @classmethod
    def ok(cls, record_id: str) -> PublishResult:
        return cls(True, record_id)

    @classmethod
    def failed(cls, reason: PublishFailureReason, error: str | None = None) -> PublishResult:
        return cls(False, None, reason, error)


@dataclass(frozen=True, slots=True)
class DeadLetterMessage:
    original_message: Any
    original_message_type: str
    original_stream_key: str
    original_group: str
    original_record_id: str
    error_message: str
    error_type: str
    stack_trace: str
    timestamp: int
    source_consumer: str
    retry_count: int | None = None
    business_id: str | None = None
    priority: str | None = None


@dataclass(frozen=True, slots=True)
class BacklogInfo:
    """Stream length plus consumer-group pending summary."""

    stream: str
    length: int
    group: str | None = None
    pending: int = 0
    idle_millis: int | None = None
    consumers: tuple[str, ...] = ()


@dataclass
class ConsumerConfig:
    stream_key: str
    group: str
    consumer: str = "default-consumer"
    auto_ack: bool = True
    max_retries: int = 3
    error_strategy: ErrorStrategy = ErrorStrategy.DEAD_LETTER
    idempotency_enabled: bool = True
    dead_letter_strategy: DeadLetterStrategy = DeadLetterStrategy.GLOBAL
    count: int = 10
    block_millis: int | None = None


@dataclass
class IdempotencyProperties:
    key_prefix: str = "idemp:stream:"
    memory_ttl_seconds: float = 3600.0
    redis_ttl_seconds: float = 86400.0


@dataclass
class StreamEntry:
    """Raw decoded entry used internally by the bus."""

    id: str
    fields: dict[str, str] = field(default_factory=dict)


__all__ = [
    "BacklogInfo",
    "ConsumerConfig",
    "DeadLetterMessage",
    "DeadLetterStrategy",
    "ErrorStrategy",
    "EventContext",
    "IdempotencyProperties",
    "PublishFailureReason",
    "PublishResult",
    "StreamEntry",
    "StreamMessage",
]
