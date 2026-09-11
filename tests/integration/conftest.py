"""跨组件集成测试的共享 fixtures（Phase D）。

中文
----
集中管理以下跨多个测试文件复用的资源：

- **真实 Redis 客户端**：`redis_url` / `redis_available` / `requires_redis`。
  集成测试在真实 Redis（端口 16379）上做多组件联调；Redis 不可达时
  整个集成套件自动 skip（与 `cache-redis` 单元测试保持一致）。
- **`RedisProviderRegistrar` 实例**：`redis_registrar`，`module` scope
  复用，避免每个 test case 都重新连接 + 重新构造 16 个 manager。
- **测试 namespace**：`redis_namespace`（每模块唯一 hex），所有写入
  都限定在该 namespace 下，teardown 时按 `SCAN` 删除。
- **`MockTransport` IdP 句柄**：`mock_idp` 提供 `httpx.MockTransport` 的
  工厂与 helper，方便 oauth / http 测试共享同一套 token-issuer 桩。

English
--------
Workspace-level shared fixtures for the cross-component integration
test suite. Provides:

- **Real Redis client**: `redis_url` / `redis_available` /
  `requires_redis`. Integration tests run against a real Redis
  (port 16379); unreachable Redis → entire suite skips (matches
  `cache-redis` unit-test convention).
- **`RedisProviderRegistrar` instance**: `redis_registrar`,
  `module`-scoped to avoid re-connecting + rebuilding 16 managers
  per test case.
- **Test namespace**: `redis_namespace` (unique hex per module);
  every write is scoped to the namespace, and teardown SCAN-deletes
  all keys under it.
- **`MockTransport` IdP handle**: `mock_idp` factory + helpers so
  oauth / http tests share the same token-issuer stub.
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import redis as redis_lib
import redis.exceptions as redis_exc

# Default test Redis URL (matches components/cache/cache-redis/tests/conftest.py).
DEFAULT_REDIS_URL = "redis://:Redis2025!Local@127.0.0.1:16379/0"
REDIS_URL = os.environ.get("ATLAS_RICHIE_CACHE_REDIS_URL", DEFAULT_REDIS_URL)


# ── Redis reachability ─────────────────────────────────────────────


def _is_redis_reachable(url: str) -> bool:
    """Quick TCP probe for the test Redis. Mirrors the cache-redis
    `conftest.py` helper so the integration suite skips cleanly when
    no test Redis is available.
    """
    try:
        rest = url.split("://", 1)[1]
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        host_port = rest.split("/", 1)[0]
        if ":" in host_port:
            host, port = host_port.rsplit(":", 1)
        else:
            host, port = host_port, 6379
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except (OSError, ValueError):
        return False


# ── Session-scoped fixtures ────────────────────────────────────────


@pytest.fixture(scope="session")
def redis_url() -> str:
    """Redis URL for the integration suite (env-overridable)."""
    return REDIS_URL


@pytest.fixture(scope="session")
def redis_available(redis_url: str) -> bool:
    """Whether the test Redis is reachable on this machine."""
    return _is_redis_reachable(redis_url)


@pytest.fixture
def requires_redis(redis_available: bool, redis_url: str) -> None:
    """Skip a test if the test Redis is unreachable.

    Mirrors the `cache-redis` package convention; lets `pytest -m unit`
    runs skip integration tests cleanly. Function-scoped; can be
    requested directly from a test function.
    """
    if not redis_available:
        pytest.skip(
            f"Redis not reachable at {redis_url}; "
            "set ATLAS_RICHIE_CACHE_REDIS_URL or start the test Redis"
        )


# ── Module-scoped fixtures ─────────────────────────────────────────


@pytest.fixture(scope="module")
def redis_namespace() -> str:
    """Unique per-module namespace. Used as the Redis key prefix so
    one test module cannot collide with another.
    """
    return f"atlas-richie-int-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def redis_registrar(
    redis_available: bool,
    redis_url: str,
    redis_namespace: str,
) -> Iterator[Any]:
    """A module-scoped `RedisProviderRegistrar` against the test Redis.

    Reuses one connection / 16 managers across every test in a
    module — integration tests are slower than unit tests, so the
    module scope is the right granularity. Cleanup:
    SCAN-deletes all keys under the module namespace, then
    `CacheRegistry.unregister()` and `reg.close()`.

    Note: we do NOT depend on the function-scoped `requires_redis`
    fixture (scope mismatch); the reachability check is duplicated
    inline so we can `pytest.skip` from a module-scoped fixture.
    """
    if not redis_available:
        pytest.skip(
            f"Redis not reachable at {redis_url}; "
            "set ATLAS_RICHIE_CACHE_REDIS_URL or start the test Redis"
        )

    # Local import: cache-registrar requires Redis to be reachable.
    from atlas_richie.cache_core import CacheRegistry
    from atlas_richie.cache_redis import RedisProviderRegistrar

    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except redis_exc.RedisError as exc:
        pytest.skip(f"Redis not reachable at {redis_url!r}: {exc}")

    reg = RedisProviderRegistrar(
        client, namespace=redis_namespace, connection_string=redis_url
    )
    CacheRegistry.unregister()
    try:
        yield reg
    finally:
        try:
            keys = list(client.scan_iter(match=f"{redis_namespace}:*", count=200))
            if keys:
                client.delete(*keys)
        finally:
            CacheRegistry.unregister()
            reg.close()


@pytest.fixture(scope="module")
def installed_registrar(redis_registrar: Any) -> Iterator[Any]:
    """Module-scoped `RedisProviderRegistrar` installed into the
    global `CacheRegistry`. Lets tests use `GlobalCache.value_ops()`
    without manually wiring the registry per test.
    """
    from atlas_richie.cache_core import GlobalCache, GlobalCacheManager

    GlobalCache.install(GlobalCacheManager(redis_registrar))
    try:
        yield redis_registrar
    finally:
        GlobalCache.uninstall()


# ── HTTP mock-transport helpers ────────────────────────────────────


@pytest.fixture
def mock_idp() -> Callable[[dict[str, Any] | None], Any]:
    """Factory: returns an `httpx.MockTransport` that mimics an IdP
    token endpoint. The handler responds to `POST /token` with a
    valid OAuth 2.1 token response, and returns 400 to anything else
    unless overridden.

    The returned transport can be installed via
    `unittest.mock.patch` over `_HttpxClientFactory.create_sync`,
    exactly like the existing `test_oauth_component.py` / `test_http_client.py`
    tests do. This fixture is function-scoped so each test gets a
    fresh handler closure.
    """
    import httpx

    def _make(
        token_payload: dict[str, Any] | None = None,
    ) -> httpx.MockTransport:
        payload = token_payload or {
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "mcp.read",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/token") and request.method == "POST":
                return httpx.Response(200, json=payload, request=request)
            return httpx.Response(404, json={"error": "not_found"}, request=request)

        return httpx.MockTransport(handler)

    return _make


@pytest.fixture
def controlled_http_client() -> Callable[[Any], Any]:
    """Factory: returns a `unittest.mock.patch` context manager that
    redirects `HttpClient` to use the supplied `httpx.MockTransport`.
    Tests use this exactly the way `test_http_client.py` does:

        with controlled_http_client(mock_idp({...})):
            with HttpClient() as client:
                ...
    """
    import unittest.mock
    import httpx
    from atlas_richie.http.client import _HttpxClientFactory

    def _patcher(transport: httpx.BaseTransport) -> Any:
        return unittest.mock.patch(
            "atlas_richie.http.client._HttpxClientFactory.create_sync",
            return_value=httpx.Client(transport=transport),
        )

    return _patcher
