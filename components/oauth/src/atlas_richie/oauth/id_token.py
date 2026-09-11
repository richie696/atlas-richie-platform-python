"""OIDC ID Token 校验与 OIDC 特定 claim 检查。
----
`IdTokenValidator` 复用 `TokenValidator` 完成签名 + 标准 JWT claim
校验，再叠加 OIDC Core 1.0 §3.1.3.7 中"不属于通用 OAuth access
token 路径"的检查：

- `nonce`：防止 ID Token 跨请求重放。
- `auth_time` + `max_age`：强制最大认证时间窗口。
- `at_hash`：与本次 access_token 绑定的 SHA-256 前半截哈希。
- `c_hash`：与本次授权码绑定的同算法哈希。

为什么这层检查不放在通用 `TokenValidator` 上：access token 路径
不需要这四个 claim，硬塞上去会让 JWT 验证器对 OAuth 资源服务器
产生误用。`IdTokenValidator` 是 OIDC 流程专用入口，依赖
`TokenValidator` 提供基础签名校验，自己只负责 OIDC 特定部分。

English
--------
OIDC ID Token validation and OIDC-specific claim checks.

`IdTokenValidator` reuses a `TokenValidator` for signature and
standard JWT claim checks, then layers the OIDC Core 1.0 §3.1.3.7
checks that do not belong on the generic OAuth access-token path:

- `nonce` — prevents ID Token replay across requests.
- `auth_time` + `max_age` — enforces a maximum authentication
  freshness window.
- `at_hash` — SHA-256 left-half hash bound to this access token.
- `c_hash` — same algorithm bound to this authorization code.

Why these checks are not on the generic `TokenValidator`: the
access-token path does not need any of these four claims, and
forcing them onto a JWT validator would let it be misused from the
OAuth resource-server side. `IdTokenValidator` is the OIDC-only
entry point — it depends on `TokenValidator` for signature /
standard-claim validation and only owns the OIDC-specific layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from .dpop import access_token_hash
from .errors import OAuthConfigurationError, OAuthTokenValidationError
from .models import AuthenticatedPrincipal
from .resource import TokenValidator


def code_hash(code: str) -> str:
    """中文
    ----
    返回授权码的 OIDC `c_hash`。

    算法与 `access_token_hash` 一致：SHA-256 左半段、base64url
    编码、去 padding。

    English
    --------
    Return the OIDC `c_hash` for an authorization code.

    Same algorithm as `access_token_hash`: left-most half of
    SHA-256, base64url-encoded without padding.
    """
    if not code:
        raise OAuthConfigurationError("authorization code is required")
    digest = hashlib.sha256(code.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class IdTokenValidator:
    """中文
    ----
    用 OIDC 特定的 claim 检查校验 ID Token。

    Attributes:
        jwt_validator: 一个 `TokenValidator`，负责签名验证与
            标准 JWT claim 检查（iss / aud / exp / sub）。
            OIDC 特定检查在本类内，叠加在它返回的 principal 之上。
        expected_issuer: ID Token 必须携带的精确 `iss` claim。
        expected_audience: 必须出现在 `aud` 中的受众。
        expected_client_id: 设置后，ID Token 的 `client_id`
            （或 `azp`）必须等于该值。
        clock_skew: 应用于 `exp` / `iat` / `auth_time` / `max_age`
            检查的容忍时钟偏差。

    English
    --------
    Validates an OIDC ID Token with OIDC-specific claim checks.

    Attributes:
        jwt_validator: A `TokenValidator` that performs signature
            verification and standard JWT claim checks (iss, aud,
            exp, sub). The OIDC-specific checks live in this class
            and are applied on top of the principal it returns.
        expected_issuer: The exact `iss` claim the ID Token must
            carry.
        expected_audience: The audience that must appear in `aud`.
        expected_client_id: When set, the ID Token's `client_id`
            (or `azp`) must equal this value.
        clock_skew: Tolerated clock skew applied to `exp`, `iat`,
            `auth_time`, and `max_age` checks.
    """

    jwt_validator: TokenValidator
    expected_issuer: str
    expected_audience: str
    expected_client_id: str | None = None
    clock_skew: timedelta = timedelta(seconds=30)

    def __post_init__(self) -> None:
        if self.jwt_validator is None:
            raise ValueError("jwt_validator is required")
        if not self.expected_issuer or not self.expected_audience:
            raise ValueError("expected_issuer and expected_audience are required")
        if self.clock_skew < timedelta():
            raise ValueError("clock_skew must be non-negative")

    def validate(
        self,
        id_token: str,
        *,
        expected_nonce: str | None = None,
        max_age_seconds: int | None = None,
        access_token: str | None = None,
        code: str | None = None,
        now: datetime | None = None,
    ) -> AuthenticatedPrincipal:
        """中文
        ----
        校验 ID Token 并返回已认证的 principal。

        Args:
            id_token: 待校验的紧凑 JWS ID Token。
            expected_nonce: 若提供，ID Token 的 `nonce` claim 必须
                等于该值（OIDC §3.1.3.7 第 6 步）。
            max_age_seconds: 若提供，自 `auth_time` 起的经过时间
                不得超过该值（加 clock_skew）。
                OIDC §3.1.3.7 第 8 步。
            access_token: 若提供且 ID Token 携带 `at_hash`，该哈希
                必须与本 access token 匹配。OIDC §3.1.3.7 第 11 步。
            code: 若提供且 ID Token 携带 `c_hash`，该哈希必须与本
                授权码匹配。OIDC §3.1.3.7 第 12 步。
            now: 时间相关检查的墙钟锚点；`None` 时使用
                `datetime.now(UTC)`。测试 seam。

        English
        --------
        Validate an ID Token and return the authenticated principal.

        Args:
            id_token: The compact JWS ID Token to verify.
            expected_nonce: When provided, the ID Token's `nonce`
                claim must equal this value. OIDC §3.1.3.7 step 6.
            max_age_seconds: When provided, the time elapsed since
                `auth_time` must not exceed this value (plus clock
                skew). OIDC §3.1.3.7 step 8.
            access_token: When provided and the ID Token carries
                `at_hash`, the hash must match this access token.
                OIDC §3.1.3.7 step 11.
            code: When provided and the ID Token carries `c_hash`,
                the hash must match this authorization code. OIDC
                §3.1.3.7 step 12.
            now: Wall-clock anchor for time-based checks. When
                `None`, `datetime.now(UTC)` is used. Test seam.
        """
        if not id_token:
            raise OAuthTokenValidationError("ID Token is required")
        principal = self.jwt_validator.validate(id_token)
        self._check_expected_principal(principal)
        self._check_nonce(principal.claims, expected_nonce)
        self._check_max_age(principal.claims, max_age_seconds, now)
        self._check_at_hash(principal.claims, access_token)
        self._check_c_hash(principal.claims, code)
        return principal

    def _check_expected_principal(self, principal: AuthenticatedPrincipal) -> None:
        if principal.issuer != self.expected_issuer:
            raise OAuthTokenValidationError("ID Token issuer is not accepted")
        if self.expected_audience not in principal.audience:
            raise OAuthTokenValidationError("ID Token audience is not accepted")
        if self.expected_client_id is not None and principal.client_id != self.expected_client_id:
            raise OAuthTokenValidationError("ID Token client_id is not accepted")

    def _check_nonce(
        self, claims: Mapping[str, Any], expected_nonce: str | None
    ) -> None:
        if expected_nonce is None:
            return
        actual = claims.get("nonce")
        if not isinstance(actual, str) or not hmac.compare_digest(actual, expected_nonce):
            raise OAuthTokenValidationError("ID Token nonce does not match")

    def _check_max_age(
        self,
        claims: Mapping[str, Any],
        max_age_seconds: int | None,
        now: datetime | None,
    ) -> None:
        if max_age_seconds is None:
            return
        auth_time = _require_int_claim(claims, "auth_time", "ID Token")
        anchor = now if now is not None else datetime.now(UTC)
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        elapsed = int(anchor.timestamp()) - auth_time
        if elapsed > max_age_seconds + int(self.clock_skew.total_seconds()):
            raise OAuthTokenValidationError("ID Token exceeds max_age")

    def _check_at_hash(
        self, claims: Mapping[str, Any], access_token: str | None
    ) -> None:
        at_hash = claims.get("at_hash")
        if at_hash is None:
            return
        if access_token is None:
            raise OAuthTokenValidationError("ID Token carries at_hash but no access_token was supplied")
        if not isinstance(at_hash, str) or not hmac.compare_digest(at_hash, access_token_hash(access_token)):
            raise OAuthTokenValidationError("ID Token at_hash does not match access_token")

    def _check_c_hash(
        self, claims: Mapping[str, Any], code: str | None
    ) -> None:
        c_hash = claims.get("c_hash")
        if c_hash is None:
            return
        if code is None:
            raise OAuthTokenValidationError("ID Token carries c_hash but no code was supplied")
        if not isinstance(c_hash, str) or not hmac.compare_digest(c_hash, code_hash(code)):
            raise OAuthTokenValidationError("ID Token c_hash does not match code")


def _require_int_claim(claims: Mapping[str, Any], name: str, owner: str) -> int:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise OAuthTokenValidationError(f"{owner} {name} must be an integer epoch value")
    return int(value)
