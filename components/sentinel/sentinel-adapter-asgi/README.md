# atlas-richie-sentinel-adapter-asgi

Pure ASGI 3.0 middleware for Atlas Richie Sentinel. **No
Starlette / FastAPI dependency** — works with any ASGI 3.0
framework (Starlette, FastAPI, Quart, aiohttp, raw uvicorn).

## Install

```bash
uv add atlas-richie-sentinel-adapter-asgi
```

## Usage

```python
from atlas_richie.sentinel import SentinelEngine
from atlas_richie.sentinel_adapter_asgi import SentinelASGIMiddleware

engine = SentinelEngine()
# Add slots, configure rules, etc.

app = SentinelASGIMiddleware(
    app=your_asgi_app,
    engine=engine,
)

# Run with uvicorn:
#   uvicorn mymodule:app --lifespan on
```

Completed HTTP request counts and bounded response-time histograms can be
collected locally by injecting an optional producer:

```python
from atlas_richie.sentinel_adapter_asgi import ASGIHttpMetrics

http_metrics = ASGIHttpMetrics()
app = SentinelASGIMiddleware(
    app=your_asgi_app,
    engine=engine,
    http_metrics=http_metrics,
)

# Read an immutable process-local cumulative snapshot from a trusted host
snapshot = http_metrics.snapshot()
```

The producer counts a request only after its final response body, successful
`http.response.pathsend`, or final response trailer (when enabled) has been
sent successfully. It records all
HTTP status outcomes, retains no route/status/header/body/identity labels,
and keeps only a bounded latency histogram. This is not a Reporter,
Collector, dashboard query source, or cross-process aggregate; no network or
wire protocol is involved.

## Features

- **Pure ASGI 3.0** — no framework coupling.
- **Streaming body** — chunks forwarded one at a time; lease
  released only after body EOF (no premature release).
- **Client disconnect** — `asyncio.CancelledError` during downstream
  call updates entry outcome to CANCELLED.
- **lifespan protocol** — Engine entered at lifespan startup,
  closed at shutdown with graceful timeout.
- **Resource naming** — default `"{METHOD} {path}"` (e.g.
  `"GET /orders/123"`); pluggable via `naming=` parameter.
- **Origin** — default reads `X-Forwarded-User`; pluggable via
  `origin_resolver=`.
- **Optional process-local HTTP metrics** — completed-request counter and
  mergeable bounded latency histogram; disabled unless `http_metrics=` is
  supplied.

## License

Apache-2.0.
