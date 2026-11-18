"""Redis Streams message bus: idempotent consumption, consumer groups, retry-to-DLQ.

A Python-native implementation of the Java module's semantics, not a line-by-line
port. Monitoring, tracing and the Reactor control bus are out of scope.
"""

import importlib.metadata

from .bus import DEFAULT_MAX_LEN, RedisStreamBus, dead_letter_streams
from .cleanup import CleanupReport, StreamCleanup, default_holder_id
from .consumer import PollOutcome, StreamConsumer
from .idempotency import IdempotencyGuard
from .model import (
    BacklogInfo,
    ConsumerConfig,
    DeadLetterMessage,
    DeadLetterStrategy,
    ErrorStrategy,
    EventContext,
    IdempotencyProperties,
    PublishFailureReason,
    PublishResult,
    StreamMessage,
)

__version__ = importlib.metadata.version("atlas-richie-redis-streammq")

__all__ = [
    "CleanupReport",
    "StreamCleanup",
    "default_holder_id",
    "DEFAULT_MAX_LEN",
    "BacklogInfo",
    "ConsumerConfig",
    "DeadLetterMessage",
    "DeadLetterStrategy",
    "ErrorStrategy",
    "EventContext",
    "IdempotencyGuard",
    "IdempotencyProperties",
    "PollOutcome",
    "PublishFailureReason",
    "PublishResult",
    "RedisStreamBus",
    "StreamConsumer",
    "StreamMessage",
    "__version__",
    "dead_letter_streams",
]
