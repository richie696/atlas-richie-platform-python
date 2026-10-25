# Atlas Richie Sentinel Reporter V2

Optional Metrics Reporting V2 integration. The core
`atlas-richie-sentinel` distribution remains free of network and third-party
runtime dependencies. This extension maps the public local reporting boundary
to the frozen shared wire contract, sends over the owned HTTP component with
verified mutual TLS, rotates credential generations, and retires payloads only
after validating an exact durable Collector receipt.

```python
from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.metrics.registry import MetricRegistry
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.reporting import MetricsCaptureAdapter

# Build the reporter with its configured HTTPS endpoint and mTLS credential provider.
capture = MetricsCaptureAdapter(reporter)
registry = MetricRegistry(sink=capture.metric_sink)
engine = SentinelEngine(metric_registry=registry)

await reporter.start()
try:
    async with engine, engine.entry(Resource("orders")):
        await handle_order()
finally:
    await reporter.aclose()
```

`MetricsCaptureAdapter`, `MetricsReportingPort`, and the typed local capture
values are exposed by `atlas_richie.sentinel.reporting`; the extension does not
import Sentinel's private modules. The local enqueue path is bounded and does
not perform network or disk I/O. Collector authentication, SQL durability,
retention, and multi-reporter query aggregation remain separate server-side
acceptance work.
