# atlas-richie-sentinel-reporter-rules

Optional Python Runtime producer and HTTPS/mTLS reporter for Rule Publication
Receipt V1. It translates only successful, atomically applied
`RuleSnapshotAppliedEvent` facts with managed target provenance. It does not
decide whether a rule is valid, publish rules to a configuration provider, or
persist receipts locally.

## Responsibilities

- `RulePublicationReceiptProducer` creates one immutable Receipt V1 byte body
  per managed target and owns its process-epoch sequence.
- `RulePublicationReceiptReporter` subscribes to the existing
  `RuleRepository` apply event, performs a short locked admission into a bounded
  in-memory queue, and serially retries the same bytes.
- `RulePublicationReceiptHttpTransport` sends those bytes over HTTPS with a
  rotating mTLS credential and accepts only HTTP 204 as Collector durable ACK.
- Queue size, attempts, retry delay, shutdown drain, losses, and delivery
  counters are explicit and finite.

The component is optional and has no effect unless the host explicitly creates
and starts it. It depends on the public Sentinel event, shared contracts, and
the `atlas-richie-http` facade; it does not expose HTTPX types.

## Delivery and loss semantics

The Repository callback never waits for network I/O or queue capacity. A batch
that cannot fit is dropped atomically and increments `queue_full`. Temporary
network and selected Collector failures retry with bounded exponential backoff;
each retry reuses the identical encoded body and receipt ID. A permanent
Collector rejection or exhausted retry budget increments `delivery_failed`.
Shutdown stops new admission, drains for a bounded interval, and counts any
remaining items in `abandoned_on_close`.

This is deliberately an in-memory queue: a process crash can lose receipts that
have not received Collector HTTP 204. It is not a durable local outbox. The
Collector commits its receipt inbox and outbox atomically before returning 204;
the Console worker then projects from that durable outbox.

## Host lifecycle

The host creates its enrollment-backed TLS credential provider and endpoint,
then starts the reporter with the same `RuleRepository` supplied to the
engine's selected source lifecycle:

```python
reporter = RulePublicationReceiptReporter(producer, transport)
await reporter.start(repository)
```

On shutdown, close it before closing the event loop:

```python
await reporter.aclose()
```

The TLS context must validate the Collector hostname and trust chain and carry
the active client certificate. Credential generation changes replace the
owned HTTP connection pool. No bearer token, instance identity header, raw
response body, or credential material is sent or logged by this adapter.

The package is not published yet; distribution remains gated on the Sentinel
milestone and its complete provider, persistence, replay, and acceptance
criteria.
