# atlas-richie-redis-streammq

Redis Streams message bus: publish, consumer groups, idempotent consumption,
retry-to-dead-letter and backlog inspection.

This is a **Python-native implementation of the Java module's semantics**, not a
line-by-line port. The Java `atlas-richie-redis-streammq` is 8453 lines built on
Reactor; its monitoring endpoints, metrics, tracing wrappers, control bus and
cleanup scheduler are deliberately out of scope.

Runtime dependency: `redis` only. It does **not** depend on `atlas-richie-cache-redis`
— installing this package does not pull the cache facade.

## Usage

```python
import redis
from atlas_richie.redis_streammq import ConsumerConfig, RedisStreamBus, StreamConsumer

bus = RedisStreamBus(redis.Redis.from_url("redis://localhost:6379/0"))
bus.ensure_group("orders", "workers", start_id="0")
bus.publish("orders", {"order_id": 1}, business_id="order-1")

def handle(message):
    process(message.body)

consumer = StreamConsumer(bus, ConsumerConfig("orders", "workers"), handle)
outcome = consumer.poll_once()   # processed / skipped_duplicate / dead_lettered / awaiting_retry
```

`poll_once` is synchronous and bounded; a production deployment supplies its own
scheduler or loop (`run(max_polls)` is provided for bounded driving).

## Wire format

One stream entry per message: `body` (JSON), `type` (Python type name), and
optional `business_id` / `priority`. Dead-letter entries carry the original
message plus `error_type`, `error_message`, `stack_trace`, `retry_count`,
`original_stream_key` / `original_group` / `original_record_id` and `timestamp`.

## Semantics taken from Java

- **Idempotency guard** is two-level: an in-memory fast path (default TTL 1h) plus
  a Redis `SET NX` placeholder (default TTL 24h), key prefix `idemp:stream:`.
  Crucially it **fails open**: when Redis is unavailable it records in memory and
  allows the message once, rather than rejecting everything.
- The idempotency key is the message's `business_id`, falling back to the record id.
  Duplicates are acked away so they do not linger as pending.
- **Dead-letter routing** key names match `DeadLetterQueueUtil` exactly:
  `dlq:global`, `dlq:type:<SimpleTypeName>`, `dlq:stream:<sourceStream>`, and
  `HYBRID` writes to all three.
- Consumer defaults mirror the Java `ConsumerConfig`: `consumer="default-consumer"`,
  `auto_ack=True`, `max_retries=3`, `idempotency_enabled=True`, stream trim
  `maxlen≈3000`.

## Deliberate deviations

- **Retry and idempotency interact**: the claim is acquired before processing, but
  **released when a retry is due**. Without that release every retry would look
  like a duplicate and be acked away, so retry-to-DLQ could never trigger. A
  terminal outcome (success, dead-letter, or skip) keeps the claim.
- **Retry accounting uses Redis' own pending delivery count** (`XPENDING`), so it
  survives restarts and is shared across consumers in a group, instead of a
  process-local counter. Counts are read *after* the reads, because re-delivering
  a pending entry increments the counter — a pre-read snapshot would lag by one.
- `error_strategy` defaults to `DEAD_LETTER` (Java defaults to `SKIP`) because
  retry-to-DLQ is the behaviour this port provides. `SKIP` remains available and
  acks exhausted messages away.
- `PublishFailureReason` replaces Reactor-specific reasons (`SINK_TERMINATED`,
  `BUFFER_OVERFLOW`, `OPERATION_CANCELLED`, `NON_SERIALIZED_ACCESS`) with
  transport-level ones (`REDIS_ERROR`, `SERIALIZATION_ERROR`, `UNKNOWN_ERROR`).
- Publish and dead-letter failures are returned/logged, not raised.
- Stream trimming defaults to Redis' **approximate** `MAXLEN` (it removes whole
  radix nodes, so the cap is best-effort). Pass `approximate_trimming=False` for
  an exact cap.
- No Reactor, no concurrency pool, no monitoring/tracing/control-bus surface.

## Tests

Pure-logic tests (DLQ routing, idempotency including the outage path, publish
failure results) run without Redis. Bus and consumer behaviour is tested against a
real Redis and **skips cleanly** when none is reachable; point
`ATLAS_RICHIE_STREAMMQ_REDIS_URL` at your instance.
