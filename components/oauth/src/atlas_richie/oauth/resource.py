"""Framework-neutral 资源服务器认证编排。
----
`ResourceServerAuthenticator` 是 resource-server 侧的"接受还是
拒绝"门面：输入一个 access_token，输出 `AuthenticatedPrincipal` 或
抛 `OAuthTokenValidationError`。

**两层校验策略**：

1. 优先走本地 `TokenValidator`（JWT 路径），不暴露对端。
2. 本地路径抛 `OAuthTokenValidationError` 时，根据
   `introspection_fallback` 决定是否兜底走 introspection 远端
   校验。
3. introspection 也配置缺失时，直接报"无有效路径"。

**为什么用 Protocol 而不是直接 import JOSE 库**：业务代码可能用
PyJWT、joserfc、authlib 中的任意一个。把 `TokenValidator`
抽象成 Protocol 后，框架对 JOSE 实现零依赖，业务侧自由选择
适配器即可。

**DPoP 绑定**：DPoP-bound token 必须携带 `cnf.jkt`，否则拒收。
这条与 RFC 9449 §5 / RFC 8705 token-to-key 绑定一致。

English
--------
Framework-neutral resource-server authentication orchestration.

`ResourceServerAuthenticator` is the "accept or reject" facade on
the resource-server side: input an access token, return an
`AuthenticatedPrincipal` or raise `OAuthTokenValidationError`.

**Two-layer validation strategy:**

1. Prefer the local `TokenValidator` (JWT path) — no network call.
2. When the local path raises `OAuthTokenValidationError`, fall
   back to the configured introspection client only if
   `introspection_fallback` is `True`.
3. If introspection is also unconfigured, raise "no accepted
   validation path".

**Why a Protocol, not a direct JOSE import:** business code may
use PyJWT, joserfc, or authlib. Abstracting `TokenValidator` as a
Protocol keeps the framework JOSE-implementation-agnostic;
business code wires the adapter of its choice.

**DPoP binding:** DPoP-bound tokens must carry `cnf.jkt`; missing
binding is rejected. This matches RFC 9449 §5 and RFC 8705
token-to-key confirmation.
"""

from __future__ import annotations

from typing import Protocol

from .client import IntrospectionClient
from .dpop import DpopProofVerifier
from .errors import OAuthTokenValidationError
from .models import AuthenticatedPrincipal, OAuthClientCredentials


class TokenValidator(Protocol):
    """中文
    ----
    校验 bearer token，仅返回 framework-neutral principal 数据。

    English
    --------
    Validate a bearer token and return only framework-neutral
    principal data.
    """

    def validate(self, access_token: str) -> AuthenticatedPrincipal:
        """中文
        ----
        无效或不可接受的 token 抛 `OAuthTokenValidationError`。

        English
        --------
        Raise `OAuthTokenValidationError` for an invalid or
        unacceptable token.
        """


class ResourceServerAuthenticator:
    """中文
    ----
    JWT 优先、introspection 可选兜底的外观；与 Java 组件的流程 1:1
    对齐。

    English
    --------
    JWT-first, optional introspection-fallback façade mirroring the
    Java component flow.
    """

    def __init__(
        self,
        jwt_validator: TokenValidator | None,
        *,
        introspection_client: IntrospectionClient | None = None,
        introspection_endpoint: str | None = None,
        introspection_credentials: OAuthClientCredentials | None = None,
        expected_issuer: str | None = None,
        expected_audience: str | None = None,
        introspection_fallback: bool = True,
    ) -> None:
        self._jwt_validator = jwt_validator
        self._introspection_client = introspection_client
        self._introspection_endpoint = introspection_endpoint
        self._introspection_credentials = introspection_credentials
        self._expected_issuer = expected_issuer
        self._expected_audience = expected_audience
        self._introspection_fallback = introspection_fallback

    def authenticate(self, access_token: str) -> AuthenticatedPrincipal:
        if not access_token:
            raise OAuthTokenValidationError("access token is required")
        if self._jwt_validator is not None:
            try:
                return self._jwt_validator.validate(access_token)
            except OAuthTokenValidationError:
                if not self._introspection_fallback:
                    raise
        if self._introspection_client is None or self._introspection_endpoint is None or self._introspection_credentials is None:
            raise OAuthTokenValidationError("no accepted resource-server validation path is configured")
        result = self._introspection_client.introspect(
            self._introspection_endpoint,
            self._introspection_credentials,
            access_token,
        )
        if not result.active or not result.subject or not result.issuer:
            raise OAuthTokenValidationError("access token is inactive")
        if self._expected_issuer is not None and result.issuer != self._expected_issuer:
            raise OAuthTokenValidationError("access token issuer is not accepted")
        if self._expected_audience is not None and self._expected_audience not in result.audience:
            raise OAuthTokenValidationError("access token audience is not accepted")
        return AuthenticatedPrincipal(
            subject=result.subject,
            client_id=result.client_id,
            issuer=result.issuer,
            audience=result.audience,
            scopes=result.scopes,
            expires_at=result.expires_at,
            token_id=result.token_id,
            claims=result.claims,
        )

    def authenticate_dpop(
        self,
        access_token: str,
        proof: str,
        *,
        method: str,
        target_uri: str,
        verifier: DpopProofVerifier,
        nonce: str | None = None,
    ) -> AuthenticatedPrincipal:
        """中文
        ----
        认证 DPoP 绑定的 token；缺失 `cnf.jkt` 直接拒收。

        English
        --------
        Authenticate a DPoP-bound token and reject missing
        `cnf.jkt` binding.
        """

        principal = self.authenticate(access_token)
        confirmation = principal.claims.get("cnf")
        key_thumbprint = confirmation.get("jkt") if isinstance(confirmation, dict) else None
        if not isinstance(key_thumbprint, str) or not key_thumbprint:
            raise OAuthTokenValidationError("DPoP-bound access token confirmation is required")
        verifier.verify(
            proof,
            method=method,
            target_uri=target_uri,
            access_token=access_token,
            expected_key_thumbprint=key_thumbprint,
            nonce=nonce,
        )
        return principal
