"""集成测试：cache + oauth（Redis 作为 token 缓存层）。

中文
----
演示一个真实场景：`OAuthTokenClient`（`client_credentials` grant）
向 IdP 申请 access token，但把 **token 缓存**放在 Redis（由
`RedisProviderRegistrar` 提供）。多进程之间共享 token：第二个进程
调 `token_for()` 不会再去打 IdP，第三次也不会。

- 第一次 `token_for()`：缓存 miss → 调用 `OAuthTokenClient.client_credentials`
  → IdP round-trip 1 → 写入 Redis。
- 第二次 `token_for()`：缓存 hit → 0 次 IdP round-trip。
- 强制失效（`redis_caching_requester.invalidate()`）：再调一次 → IdP
  round-trip 2 → 缓存重新填充。
- 跨进程模拟：第二个 `RedisCachingTokenRequester` 实例持有同一个
  Redis namespace → 直接看到 token，不需要打 IdP。

说明：这里不直接复用 `OAuthTokenClient` 自带的 `OAuthTokenManager`
缓存，因为后者是 **进程内** 缓存；集成测试关心的是 **跨进程** 的
Redis 共享语义。

English
--------
Integration test: cache + oauth (Redis as the token-cache layer).

Demonstrates a real scenario: `OAuthTokenClient` (client-credentials
grant) issues access tokens from an IdP, but the **token cache** lives
in Redis (via `RedisProviderRegistrar`). Multiple processes share the
token: a 2nd `token_for()` doesn't talk to the IdP, nor does a 3rd.

- 1st `token_for()`: cache miss → calls
  `OAuthTokenClient.client_credentials` → 1 IdP round-trip → writes
  to Redis.
- 2nd `token_for()`: cache hit → 0 IdP round-trips.
- Forced invalidation (`redis_caching_requester.invalidate()`): next
  call → 2nd IdP round-trip → cache re-populated.
- Cross-process simulation: a 2nd `RedisCachingTokenRequester`
  instance with the same Redis namespace sees the token directly,
  no IdP round-trip.

We deliberately do NOT use `OAuthTokenManager`'s built-in cache
because that cache is **process-local**; the integration concern
here is the **cross-process** Redis sharing semantics.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from atlas_richie.http import HttpClient
from atlas_richie.oauth import (
    OAuthAccessToken,
    OAuthClientCredentials,
    OAuthTokenClient,
    OAuthTokenResponse,
    ResourceIndicator,
)

pytestmark = pytest.mark.integration


# ── Helpers ────────────────────────────────────────────────────────


def _controlled_client(transport: httpx.BaseTransport) -> Any:
    """`unittest.mock.patch` context manager that swaps the
    `_HttpxClientFactory` for a controlled `httpx.Client`.
    """
    return patch(
        "atlas_richie.http.client._HttpxClientFactory.create_sync",
        return_value=httpx.Client(transport=transport),
    )


class _IdpCountingTransport(httpx.MockTransport):
    """`MockTransport` that counts `POST /token` hits and serves a
    fresh access token each call.
    """

    def __init__(self) -> None:
        self.idp_calls: list[httpx.Request] = []
        self._counter = 0
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if not (request.url.path.endswith("/token") and request.method == "POST"):
            return httpx.Response(404, request=request)
        self.idp_calls.append(request)
        self._counter += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"idp-token-v{self._counter}",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "mcp.read",
            },
            request=request,
        )


class _RedisCachingTokenRequester:
    """`OAuthTokenRequester` 形状的 Redis-backed 缓存。

    - 缓存 key 形如 `oauth:<namespace>:<resource>:<scopes_hash>`。
    - 缓存命中时构造一个 `OAuthTokenResponse` 但 **不调** 底层
      requester。
    - 缓存未命中时调底层 requester 并把响应序列化进 Redis。
    - `invalidate()` 强制下次调用走 IdP。

    这里只缓存 `client_credentials` 路径；`refresh_token` 路径每次
    都直接打 IdP 并 invalidate 缓存。
    """

    def __init__(
        self,
        value_ops: Any,
        key_ops: Any,
        namespace: str,
        requester: Any,
    ) -> None:
        self._value_ops = value_ops
        self._key_ops = key_ops
        self._namespace = namespace
        self._requester = requester
        self.hits = 0
        self.misses = 0

    def _cache_key(self, resource: ResourceIndicator, scopes: frozenset[str]) -> str:
        # Stable, deterministic key for a (resource, scopes) tuple.
        scope_hash = base64.b64encode(
            "\x00".join(sorted(scopes)).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return f"oauth:{self._namespace}:{resource.value}:{scope_hash}"

    def client_credentials(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        key = self._cache_key(resource, scopes)
        cached = self._value_ops.get(key, dict)
        if cached is not None:
            self.hits += 1
            return _deserialize_token_response(cached)
        self.misses += 1
        response = self._requester.client_credentials(
            endpoint, credentials, resource, scopes
        )
        self._value_ops.set_with_ttl(
            key, _serialize_token_response(response), timeout_millis=300_000
        )
        return response

    def refresh_token(
        self,
        endpoint: str,
        credentials: OAuthClientCredentials,
        refresh: str,
        resource: ResourceIndicator,
        scopes: frozenset[str],
    ) -> OAuthTokenResponse:
        # Invalidate cache so the next client_credentials call
        # re-fetches; always round-trip the IdP for refresh.
        key = self._cache_key(resource, scopes)
        self._key_ops.remove_cache(key)
        return self._requester.refresh_token(
            endpoint, credentials, refresh, resource, scopes
        )

    def invalidate(
        self, resource: ResourceIndicator, scopes: frozenset[str]
    ) -> None:
        self._key_ops.remove_cache(self._cache_key(resource, scopes))


def _serialize_token_response(response: OAuthTokenResponse) -> dict[str, Any]:
    """Round-trip-safe JSON dict for `OAuthTokenResponse`.

    The token's `expires_at` (datetime) is encoded as a UTC ISO
    string so Redis stores a plain dict (no custom codecs).
    """
    token = response.token_with_granted_scopes()
    expiry_iso = (
        token.expires_at.isoformat() if token.expires_at is not None else ""
    )
    return {
        "access_token": token.value,
        "token_type": token.token_type,
        "expiry_iso": expiry_iso,
        "scopes": sorted(token.scopes),
        "resource": token.resource.value if token.resource is not None else None,
        "granted_scopes": sorted(response.granted_scopes),
        "refresh_token": response.refresh_token,
    }


def _deserialize_token_response(payload: Mapping[str, Any]) -> OAuthTokenResponse:
    if payload.get("expiry_iso"):
        expiry_dt = datetime.fromisoformat(payload["expiry_iso"])
    else:
        expiry_dt = None
    resource: ResourceIndicator | None = None
    if payload.get("resource"):
        resource = ResourceIndicator(payload["resource"])
    token = OAuthAccessToken(
        payload["access_token"],
        expires_at=expiry_dt,
        scopes=frozenset(payload.get("scopes", [])),
        resource=resource,
        token_type=payload.get("token_type", "Bearer"),
    )
    granted = frozenset(payload.get("granted_scopes", []))
    return OAuthTokenResponse(
        token,
        granted_scopes=granted,
        refresh_token=payload.get("refresh_token"),
    )


# ── Tests ──────────────────────────────────────────────────────────


class TestRedisBackedTokenCache:
    """Redis as a shared token cache for the oauth client."""

    def test_first_call_round_trips_idp_second_call_hits_cache(
        self,
        installed_registrar: Any,
        request: Any,  # pytest `request` fixture, for unique namespaces
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        transport = _IdpCountingTransport()
        # Unique per-test inner namespace so module-scoped state
        # doesn't bleed between tests.
        ns = f"oauth-test-{request.node.name.replace('[', '-').replace(']', '')}"

        with _controlled_client(transport):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                requester = _RedisCachingTokenRequester(
                    value_ops, key_ops, namespace=ns, requester=client
                )
                credentials = OAuthClientCredentials("client-1", "secret-1")
                resource = ResourceIndicator("https://api.test/mcp")
                scopes = frozenset({"mcp.read"})

                first = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )
                second = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )

        assert first.access_token.value == "idp-token-v1"
        assert second.access_token.value == "idp-token-v1"
        assert len(transport.idp_calls) == 1, "second call must come from cache"
        assert requester.hits == 1
        assert requester.misses == 1

    def test_invalidate_forces_a_refresh(
        self,
        installed_registrar: Any,
        request: Any,
    ) -> None:
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        transport = _IdpCountingTransport()
        ns = f"oauth-test-{request.node.name.replace('[', '-').replace(']', '')}"

        with _controlled_client(transport):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                requester = _RedisCachingTokenRequester(
                    value_ops, key_ops, namespace=ns, requester=client
                )
                credentials = OAuthClientCredentials("client-1", "secret-1")
                resource = ResourceIndicator("https://api.test/mcp")
                scopes = frozenset({"mcp.read"})

                first = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )
                requester.invalidate(resource, scopes)
                refreshed = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )

        assert first.access_token.value == "idp-token-v1"
        assert refreshed.access_token.value == "idp-token-v2"
        assert len(transport.idp_calls) == 2, (
            "after invalidate(), the IdP must be hit again"
        )

    def test_second_requester_instance_sees_cached_token(
        self,
        installed_registrar: Any,
        request: Any,
    ) -> None:
        """Simulate a 2nd process picking up the cached token.

        We construct a second `RedisCachingTokenRequester` over the
        same Redis namespace; it must observe the token without
        talking to the IdP.
        """
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        transport = _IdpCountingTransport()
        ns = f"oauth-test-{request.node.name.replace('[', '-').replace(']', '')}"

        with _controlled_client(transport):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                r1 = _RedisCachingTokenRequester(
                    value_ops, key_ops, namespace=ns, requester=client
                )
                r2 = _RedisCachingTokenRequester(
                    value_ops, key_ops, namespace=ns, requester=client
                )
                credentials = OAuthClientCredentials("client-1", "secret-1")
                resource = ResourceIndicator("https://api.test/mcp")
                scopes = frozenset({"mcp.read"})

                r1.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )
                r2_token = r2.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes
                )

        # Only r1 talked to the IdP; r2 picked up the cached token.
        assert r2_token.access_token.value == "idp-token-v1"
        assert len(transport.idp_calls) == 1
        assert r2.hits == 1
        assert r2.misses == 0

    def test_different_scopes_get_different_cache_entries(
        self,
        installed_registrar: Any,
        request: Any,
    ) -> None:
        """A token requested with scope A must not be served when
        scope A∩B is requested.
        """
        value_ops = installed_registrar.value_ops()
        key_ops = installed_registrar.key_ops()
        transport = _IdpCountingTransport()
        ns = f"oauth-test-{request.node.name.replace('[', '-').replace(']', '')}"

        with _controlled_client(transport):
            with HttpClient() as http_client:
                client = OAuthTokenClient(http_client)
                requester = _RedisCachingTokenRequester(
                    value_ops, key_ops, namespace=ns, requester=client
                )
                credentials = OAuthClientCredentials("client-1", "secret-1")
                resource = ResourceIndicator("https://api.test/mcp")
                scopes_a = frozenset({"mcp.read"})
                scopes_ab = frozenset({"mcp.read", "mcp.write"})

                a1 = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes_a
                )
                a1_again = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes_a
                )
                ab = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes_ab
                )
                ab_again = requester.client_credentials(
                    "https://idp.test/token", credentials, resource, scopes_ab
                )

        assert a1.access_token.value == "idp-token-v1"
        assert a1_again.access_token.value == "idp-token-v1"  # cache hit
        assert ab.access_token.value == "idp-token-v2"  # cache miss
        assert ab_again.access_token.value == "idp-token-v2"  # cache hit
        assert len(transport.idp_calls) == 2
