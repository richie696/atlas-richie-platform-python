"""OAuth 与 protected-resource metadata 外观，加一个带缓存的 JWKS 源。
----
本模块聚合三类 metadata 操作：

- **Authorization-server metadata**（RFC 8414）：通过
  `OAuthMetadataClient.authorization_server(...)` 拉取并归一化
  `issuer` / `token_endpoint` / `jwks_uri` 等字段。
- **Protected-resource metadata**（RFC 9728）：通过
  `OAuthMetadataClient.protected_resource(...)` 拉取并保留
  extension claims（`extensions`）。
- **JWKS 缓存源**：`JwkSetSource` Protocol + `HttpJwkSetSource`
  实现；进程内 `RLock` 保护 + TTL 缓存 + 显式 `refresh()` 入口
  用于"未知 kid"路径。

**协议中立性**：metadata 模块对 JOSE / token 字符串零依赖，只
关心 JWKS 文档结构。校验发生在 `resource.py` 适配器里。

**JWKS 缓存语义**：

- `get()`：未命中或 TTL 到期则 fetch；命中则返回深拷贝，避免
  业务侧改坏缓存。
- `refresh()`：跳过 TTL 强制 fetch；用于"上次没这个 kid"时重
  试一次。

English
--------
OAuth and protected-resource metadata facades plus a cached JWKS
source.

Three categories of metadata work live here:

- **Authorization-server metadata** (RFC 8414): fetched and
  normalized via
  `OAuthMetadataClient.authorization_server(...)` — `issuer`,
  `token_endpoint`, `jwks_uri`, etc.
- **Protected-resource metadata** (RFC 9728): fetched via
  `OAuthMetadataClient.protected_resource(...)` with extension
  claims preserved in `extensions`.
- **JWKS cache source:** `JwkSetSource` Protocol +
  `HttpJwkSetSource` implementation; process-local `RLock`,
  TTL cache, and an explicit `refresh()` entry for the
  "unknown kid" retry path.

**Protocol-neutrality:** this module has zero JOSE / token-string
dependencies. It only deals with the JWKS document structure;
validation happens in the adapter in `resource.py`.

**JWKS cache semantics:**

- `get()`: miss or TTL-expired triggers a fetch; on hit, a deep
  copy is returned so callers cannot mutate the cache.
- `refresh()`: skips the TTL and forces a fetch; used for the
  "didn't see this kid last time" retry path.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol

from atlas_richie.http import HttpClient, HttpRequest

from .errors import OAuthProtocolError
from .models import OAuthAuthorizationServerMetadata, OAuthProtectedResourceMetadata, ResourceIndicator
from .policy import HttpsOnlyEndpointPolicy, OAuthEndpointPolicy


class JwkSetSource(Protocol):
    """中文
    ----
    返回不可变的 JWKS 文档，并提供一次显式 rotation refresh。

    English
    --------
    Return one immutable JWKS document and allow an explicit
    rotation refresh.
    """

    def get(self) -> Mapping[str, Any]:
        """中文
        ----
        返回当前缓存或新拉取的 JWKS 文档（不可变副本）。

        English
        --------
        Return the currently cached or freshly fetched JWKS
        document.
        """

    def refresh(self) -> Mapping[str, Any]:
        """中文
        ----
        遇到未知 key identifier 时强制重拉一次。

        English
        --------
        Force a new JWKS fetch after an unknown key identifier.
        """


class OAuthMetadataClient:
    """中文
    ----
    Framework-neutral metadata 外观，持有端点校验与解析。

    English
    --------
    Framework-neutral metadata facade that owns endpoint
    validation and parsing.
    """

    def __init__(self, http_client: HttpClient, endpoint_policy: OAuthEndpointPolicy | None = None) -> None:
        self._http_client = http_client
        self._endpoint_policy = endpoint_policy or HttpsOnlyEndpointPolicy()

    def authorization_server(self, metadata_endpoint: str) -> OAuthAuthorizationServerMetadata:
        raw = self._get_json(metadata_endpoint)
        issuer = _required_text(raw, "issuer")
        return OAuthAuthorizationServerMetadata(
            issuer=issuer,
            authorization_endpoint=_optional_text(raw, "authorization_endpoint"),
            token_endpoint=_optional_text(raw, "token_endpoint"),
            jwks_uri=_optional_text(raw, "jwks_uri"),
            introspection_endpoint=_optional_text(raw, "introspection_endpoint"),
            revocation_endpoint=_optional_text(raw, "revocation_endpoint"),
            registration_endpoint=_optional_text(raw, "registration_endpoint"),
            grant_types_supported=_string_set(raw.get("grant_types_supported")),
            code_challenge_methods_supported=_string_set(raw.get("code_challenge_methods_supported")),
            scopes_supported=_string_set(raw.get("scopes_supported")),
        )

    def protected_resource(self, metadata_endpoint: str) -> OAuthProtectedResourceMetadata:
        raw = self._get_json(metadata_endpoint)
        resource = ResourceIndicator(_required_text(raw, "resource"))
        authorization_servers = _string_tuple(raw.get("authorization_servers"))
        extensions = {
            name: value
            for name, value in raw.items()
            if name not in {"resource", "authorization_servers", "scopes_supported"}
        }
        return OAuthProtectedResourceMetadata(
            resource=resource,
            authorization_servers=authorization_servers,
            scopes_supported=_string_set(raw.get("scopes_supported")),
            extensions=extensions,
        )

    def _get_json(self, endpoint: str) -> Mapping[str, Any]:
        self._endpoint_policy.validate(endpoint)
        response = self._http_client.execute(HttpRequest.get(endpoint, headers={"Accept": "application/json"}))
        response.require_success()
        raw = response.json()
        if not isinstance(raw, Mapping):
            raise OAuthProtocolError("OAuth metadata response must be a JSON object")
        return raw


class HttpJwkSetSource:
    """中文
    ----
    线程安全的进程内 JWKS 缓存，提供一次由调用方控制的 refresh
    路径。

    English
    --------
    Thread-safe in-process JWKS cache with one caller-controlled
    refresh path.
    """

    def __init__(
        self,
        http_client: HttpClient,
        jwks_uri: str,
        *,
        cache_ttl: timedelta = timedelta(minutes=5),
        endpoint_policy: OAuthEndpointPolicy | None = None,
    ) -> None:
        if cache_ttl <= timedelta():
            raise ValueError("cache_ttl must be positive")
        self._http_client = http_client
        self._jwks_uri = jwks_uri
        self._cache_ttl = cache_ttl
        self._endpoint_policy = endpoint_policy or HttpsOnlyEndpointPolicy()
        self._lock = RLock()
        self._document: Mapping[str, Any] | None = None
        self._expires_at: datetime | None = None

    def get(self) -> Mapping[str, Any]:
        with self._lock:
            if self._document is None or self._expires_at is None or self._expires_at <= datetime.now(UTC):
                return self._fetch_locked()
            return deepcopy(self._document)

    def refresh(self) -> Mapping[str, Any]:
        with self._lock:
            return self._fetch_locked()

    def _fetch_locked(self) -> Mapping[str, Any]:
        self._endpoint_policy.validate(self._jwks_uri)
        response = self._http_client.execute(HttpRequest.get(self._jwks_uri, headers={"Accept": "application/json"}))
        response.require_success()
        raw = response.json()
        if not isinstance(raw, Mapping) or not isinstance(raw.get("keys"), list):
            raise OAuthProtocolError("JWKS response must contain a keys array")
        self._document = deepcopy(dict(raw))
        self._expires_at = datetime.now(UTC) + self._cache_ttl
        return deepcopy(self._document)


def _required_text(raw: Mapping[str, Any], field: str) -> str:
    value = _optional_text(raw, field)
    if value is None:
        raise OAuthProtocolError(f"OAuth metadata is missing {field}")
    return value


def _optional_text(raw: Mapping[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OAuthProtocolError(f"OAuth metadata field {field} must be a non-blank string")
    return value


def _string_set(value: object) -> frozenset[str]:
    return frozenset(_string_tuple(value))


def _string_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise OAuthProtocolError("OAuth metadata string-list fields must be arrays of non-blank strings")
    return tuple(value)
