# Atlas Richie Sentinel Incident Reporter

Optional outbound support for the independent Incident Event V1 protocol.
The Runtime calls `IncidentEventProducer` after its own explicit incident
decision, supplying the typed fact, threshold, and severity. The producer binds
the event to the shared process epoch and creates a UTC timestamp and event ID;
it does not sample metrics, infer thresholds, run an alert policy, or send
Metric V2 records. The immutable event can be retained by the caller and
submitted more than once with the same event ID if the delivery result is
uncertain.

`IncidentEventReporter.report(event)` encodes the event once, performs bounded
identical-body retries, and returns only after the Collector ACK matches the
event ID and exact request digest. `IncidentEventHttpTransport` sends over
verified HTTPS/mTLS, rotates client pools when the credential generation
changes, and never puts reporter identity or credential material in headers or
the event body. The caller owns when to await the network operation.

This package does not add automatic background scheduling or a local event
queue. Runtime event detection policy, protocol negotiation, durable Collector
storage, and Dashboard readback remain separately configured capabilities.
