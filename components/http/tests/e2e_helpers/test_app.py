"""A minimal FastAPI test app for `atlas-richie-http` E2E tests.

中文
----
E2E 测试用的最小 FastAPI 应用：覆盖 GET / POST / 流式 / 错误 /
计数等真实服务端点。**只 import FastAPI**；对 `atlas-richie-http`
的 client 端 API 零依赖,避免循环引用。

English
--------
Minimal FastAPI app used by the E2E suite to exercise the
real-server portion of `atlas-richie-http`:

- `GET /hello`           — fixed JSON response.
- `POST /echo`           — echoes the JSON body verbatim.
- `GET /slow?ms=N`       — sleeps `N` ms (default 100), then 200.
- `GET /error`           — always returns 500 with a JSON body.
- `GET /chunked?n=K`     — streams `K` newline-delimited chunks.
- `GET /counted`         — increments a process-local counter so
                            the test can assert it really saw N
                            requests (no client-side caching).

Endpoints are intentionally side-effect-free apart from `/counted`
so tests can be ordered freely. Imports are deferred to module
load time so the file is fast-fail when FastAPI is missing.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


# A process-local counter for the `/counted` endpoint. Tests assert
# the real number of requests the server received; if the client
# short-circuited or the transport deduplicated, the counter would
# fall short of the asserted value.
_counter_lock = threading.Lock()
_counter_value = 0


def _next_counter() -> int:
    """Atomically increment the per-process counter and return the new value.

    English
    --------
    Atomically increment the per-process counter and return the new
    value.
    """
    global _counter_value
    with _counter_lock:
        _counter_value += 1
        return _counter_value


def reset_counter() -> None:
    """Reset the per-process counter to zero.

    Tests that depend on the counter call this in their setup so
    residual state from earlier tests does not leak.
    """
    global _counter_value
    with _counter_lock:
        _counter_value = 0


def create_app() -> FastAPI:
    """Build a fresh FastAPI app instance.

    Returns:
        A new `FastAPI` instance with all E2E routes wired.

    English
    --------
    Build a fresh FastAPI app instance. Tests should call this
    rather than relying on a module-level singleton so each test
    has an isolated router.
    """
    app = FastAPI()

    @app.get("/hello")
    async def hello() -> dict[str, str]:
        return {"hello": "world"}

    @app.post("/echo")
    async def echo(request: Request) -> Any:
        return await request.json()

    @app.get("/slow")
    async def slow(ms: int = 100) -> dict[str, Any]:
        await asyncio.sleep(ms / 1000.0)
        return {"slow": True, "ms": ms}

    @app.get("/error")
    async def error() -> Any:
        return JSONResponse(status_code=500, content={"error": "boom", "code": "internal"})

    @app.get("/chunked")
    async def chunked(n: int = 3) -> StreamingResponse:
        async def _generator() -> Any:
            for index in range(n):
                yield f"chunk-{index}\n".encode("utf-8")
                await asyncio.sleep(0)

        return StreamingResponse(_generator(), media_type="text/plain")

    @app.get("/counted")
    async def counted() -> dict[str, int]:
        return {"hits": _next_counter()}

    @app.get("/reflect-headers")
    async def reflect_headers(request: Request) -> dict[str, str]:
        """Echo the inbound request headers as a JSON map.

        Used by the interceptor E2E test to assert that the
        `X-E2E-Marker` / `X-Request-Id` headers actually left
        the client.
        """
        return {key: value for key, value in request.headers.items()}

    return app


# Module-level singleton for the uvicorn subprocess smoke test.
# The in-process ASGI tests deliberately call `create_app()` to
# get a fresh app, but the subprocess test needs a stable import
# path (`e2e_helpers.test_app:app` with `--app-dir` set to
# `tests/`).
app = create_app()
