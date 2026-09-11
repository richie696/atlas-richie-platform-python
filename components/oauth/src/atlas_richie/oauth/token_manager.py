"""线程安全、进程内 OAuth token 生命周期外观。
----
`OAuthTokenManager` 是单个 `(token_endpoint, credentials, resource)`
三元组的"refresh-or-reuse"门面：业务代码调用 `token_for(...)`，
管理器在同一进程锁内判定：

1. 已缓存的 token 是否在 clock_skew 内未过期且 scope 满足；
2. 若是则原样返回；
3. 否则按"refresh_token → client_credentials"顺序获取新 token
   并就地替换缓存。

**为什么 process-local 不做分布式**：refresh_token 的所有权是
进程级单点（一个应用实例），不存在跨进程的令牌版本协调。涉及
多实例 / 集群级令牌共享请使用外部 secret store + 显式续期调度，
而不是在管理器里加 TTL 广播。

**为什么用 RLock 不是 Lock**：`_usable()` 在持锁时被调用
（`token_for` → `_usable`），未来如果加入"持有锁的同时把旧
token 标记为 revoked"之类的二级操作，重入语义会让升级更安全。

English
--------
A thread-safe, process-local OAuth token lifecycle facade.

`OAuthTokenManager` is the "refresh-or-reuse" facade for a single
`(token_endpoint, credentials, resource)` triple. Business code
calls `token_for(...)`; the manager, under a single process lock,
decides:

1. whether the cached token is unexpired (within clock skew) and
   satisfies the requested scopes;
2. if yes, return it as-is;
3. otherwise obtain a new token via `refresh_token` (if available)
   or fall back to `client_credentials`, and replace the cache
   in place.

**Why process-local, not distributed:** refresh-token ownership
is single-point per process (per application instance); there is
no cross-process token-version coordination to do. Multi-instance
or cluster-level token sharing should use an external secret store
plus explicit renewal scheduling, not TTL broadcast inside this
manager.

**Why `RLock`, not `Lock`:** `_usable()` is called under the lock
(inside `token_for`); if a future change adds a secondary
"mark the old token revoked" step while still holding the lock,
the re-entrant semantics make the upgrade safer.
"""

from __future__ import annotations

from datetime import timedelta
from threading import RLock

from .client import OAuthTokenRequester
from .errors import OAuthResourceMismatch
from .models import OAuthAccessToken, OAuthClientCredentials, OAuthTokenResponse, ResourceIndicator


class OAuthTokenManager:
    """中文
    ----
    在不向全局泄露 token 状态的前提下，复用或刷新单个资源绑定的
    token。

    English
    --------
    Reuse or refresh one resource-bound token without leaking token
    state globally.
    """

    CLOCK_SKEW = timedelta(seconds=30)

    def __init__(
        self,
        requester: OAuthTokenRequester,
        *,
        token_endpoint: str,
        credentials: OAuthClientCredentials,
        resource: ResourceIndicator,
        configured_scopes: frozenset[str] = frozenset(),
    ) -> None:
        self._requester = requester
        self._token_endpoint = token_endpoint
        self._credentials = credentials
        self._resource = resource
        self._configured_scopes = frozenset(configured_scopes)
        self._access_token: OAuthAccessToken | None = None
        self._refresh_token: str | None = None
        self._lock = RLock()

    def accept(self, response: OAuthTokenResponse) -> None:
        """中文
        ----
        交互式 authorization-code 兑换后用响应种子化 manager。

        English
        --------
        Seed the manager after an interactive authorization-code
        exchange.
        """

        with self._lock:
            token = response.token_with_granted_scopes()
            if token.resource is not None and token.resource != self._resource:
                raise OAuthResourceMismatch("cannot accept a token bound to another resource")
            self._access_token = token
            if response.refresh_token is not None:
                self._refresh_token = response.refresh_token

    def token_for(self, resource: ResourceIndicator, required_scopes: frozenset[str] = frozenset()) -> OAuthAccessToken:
        """中文
        ----
        返回当前可用的精确 resource token；必要时在同一进程锁下
        刷新。

        English
        --------
        Return a usable exact-resource token, refreshing under a
        single process lock.
        """

        if resource != self._resource:
            raise OAuthResourceMismatch("requested resource does not match this token manager")
        requested_scopes = self._configured_scopes | frozenset(required_scopes)
        with self._lock:
            if self._usable(requested_scopes):
                return self._access_token  # type: ignore[return-value]
            response = self._refresh(requested_scopes)
            self._access_token = response.token_with_granted_scopes()
            if response.refresh_token is not None:
                self._refresh_token = response.refresh_token
            return self._access_token

    def _usable(self, scopes: frozenset[str]) -> bool:
        return self._access_token is not None and not self._access_token.expired(self.CLOCK_SKEW) and self._access_token.supports(scopes)

    def _refresh(self, scopes: frozenset[str]) -> OAuthTokenResponse:
        if self._refresh_token is not None:
            return self._requester.refresh_token(
                self._token_endpoint,
                self._credentials,
                self._refresh_token,
                self._resource,
                scopes,
            )
        return self._requester.client_credentials(
            self._token_endpoint,
            self._credentials,
            self._resource,
            scopes,
        )
