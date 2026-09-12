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

## License

Apache-2.0.
