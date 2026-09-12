# atlas-richie-sentinel-adapter-httpx

HTTPX custom transport for Atlas Richie Sentinel.
OutboundConcurrencyGuard + metrics, no retry by default.

## Install

```bash
uv add atlas-richie-sentinel-adapter-httpx
```

## Usage

```python
import httpx
from atlas_richie.sentinel import SentinelEngine
from atlas_richie.sentinel_adapter_httpx import SentinelAsyncTransport

engine = SentinelEngine()
# Configure FlowSlot for outbound concurrency...

transport = SentinelAsyncTransport(
    engine=engine,
    flow_slot=flow_slot,
    inner_transport=httpx.AsyncHTTPTransport(),
)
client = httpx.AsyncClient(transport=transport)

resp = await client.get("https://api.example.com/orders")
```

## Defaults

- **No retry**: HTTPX's own retry middleware is independent; Sentinel
  doesn't know which operations are idempotent.
- **Resource naming**: `"{METHOD} {host}{path}"` (e.g.
  `"GET api.example.com/orders/123"`).
- **No httpcore private API**: only public `AsyncBaseTransport`.

## License

Apache-2.0.
