"""租户身份解析（对位 Java `TenantIdentityFilter` 的算法部分）。

解析优先级：assertion → JWT → unsigned header（仅当 allow_unsigned_header）。
assertion/JWT 的密码学验证由调用方注入（callable），core 不依赖任何 JWT 库。

校验链与 Java 一致：白名单放行 → 解析主体 → enforce_auth_tenant 缺失拒绝 →
tenantId==0 超管判定 → 租户存在性/状态（EXPIRED/MIGRATING/INACTIVE/
PROVISIONING）→ X-Tenant-Id header 与主体一致性。

返回 `IdentityResolution`（principal 或 error），由 Web 适配器决定如何
拒绝/绑定——core 不做 HTTP 响应。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .errors import TenantErrorCode
from .model import TenantPrincipal, TenantStatus
from .provider import TenantInfoProvider

Resolver = Callable[[Mapping[str, str]], TenantPrincipal | None]


def _ant_to_regex(pattern: str) -> re.Pattern[str]:
    escaped = re.escape(pattern).replace(r"\*\*", "\x00").replace(r"\*", "\x01")
    escaped = escaped.replace(r"\?", "\x02")
    for token, replacement in (("\x00", ".*"), ("\x01", "[^/]*"), ("\x02", "[^/]")):
        escaped = escaped.replace(token, replacement)
    escaped = re.sub(r"\\\{[^/}]+\\\}", "[^/]+", escaped)
    return re.compile(f"^{escaped}$")


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    principal: TenantPrincipal | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def denied(self) -> bool:
        return self.error_code is not None

    @property
    def bound(self) -> bool:
        return self.principal is not None and not self.denied


def _deny(code: str, message: str) -> IdentityResolution:
    return IdentityResolution(error_code=code, error_message=message)


class TenantIdentityResolver:
    def __init__(
        self,
        provider: TenantInfoProvider,
        *,
        assertion_resolver: Resolver | None = None,
        jwt_resolver: Resolver | None = None,
        allow_unsigned_header: bool = False,
        enforce_auth_tenant: bool = False,
        tenant_id_header: str = "X-Tenant-Id",
        whitelist: Sequence[str] = (),
        super_admin_paths: Sequence[str] = (),
        enabled: bool = True,
    ) -> None:
        if provider is None:
            raise ValueError("provider must not be None")
        self._provider = provider
        self._assertion = assertion_resolver
        self._jwt = jwt_resolver
        self._allow_unsigned = allow_unsigned_header
        self._enforce = enforce_auth_tenant
        self._header = tenant_id_header.lower()
        self._whitelist = [_ant_to_regex(p) for p in whitelist]
        self._super_admin = [_ant_to_regex(p) for p in super_admin_paths]
        self._enabled = enabled

    def resolve(self, path: str, headers: Mapping[str, str]) -> IdentityResolution:
        lowered = {k.lower(): v for k, v in headers.items()}
        if not self._enabled:
            return IdentityResolution()
        if any(pattern.match(path) for pattern in self._whitelist):
            return IdentityResolution()

        principal = self._assertion(lowered) if self._assertion else None
        authenticated = principal is not None
        if principal is None and self._jwt is not None:
            principal = self._jwt(lowered)
            authenticated = principal is not None
        if principal is None and self._allow_unsigned:
            principal = self._from_header(lowered)
        if principal is None:
            if self._enforce and not self._is_super_admin(path):
                return _deny(
                    TenantErrorCode.TENANT_AUTH_MISSING_TOKEN,
                    f"no tenant context for {path} (enforceAuthTenant=true)",
                )
            return IdentityResolution()

        tenant_id = principal.tenant_id
        if tenant_id == 0:
            if not authenticated or not self._is_super_admin(path):
                return _deny(
                    TenantErrorCode.TENANT_AUTH_INVALID_FORMAT,
                    "tenantId 0 requires an authenticated super-admin path",
                )
            return IdentityResolution(principal=principal)

        info = self._provider.get_tenant_info(tenant_id)
        if info is None:
            return _deny(
                TenantErrorCode.TENANT_IDENTITY_NOT_FOUND, f"tenant not found: {tenant_id}"
            )
        status_error = self._status_error(info.status, tenant_id)
        if status_error is not None:
            return status_error

        header_id = lowered.get(self._header)
        if header_id:
            try:
                if int(header_id) != tenant_id:
                    return _deny(
                        TenantErrorCode.TENANT_AUTH_MISMATCH,
                        f"header tenant {header_id} != principal tenant {tenant_id}",
                    )
            except ValueError:
                pass  # 非法 header 值仅告警，不拒绝（对位 Java）

        return IdentityResolution(principal=principal)

    def _from_header(self, headers: Mapping[str, str]) -> TenantPrincipal | None:
        raw = headers.get(self._header)
        if not raw:
            return None
        try:
            return TenantPrincipal(tenant_id=int(raw))
        except ValueError:
            return None

    def _is_super_admin(self, path: str) -> bool:
        return any(pattern.match(path) for pattern in self._super_admin)

    @staticmethod
    def _status_error(status: TenantStatus | None, tenant_id: int) -> IdentityResolution | None:
        if status is TenantStatus.EXPIRED:
            return _deny(TenantErrorCode.TENANT_AUTH_EXPIRED, f"tenant expired: {tenant_id}")
        if status is TenantStatus.MIGRATING:
            return _deny(TenantErrorCode.TENANT_MIGRATING, f"tenant migrating: {tenant_id}")
        if status is None or status is TenantStatus.INACTIVE:
            return _deny(TenantErrorCode.TENANT_AUTH_INACTIVE, f"tenant inactive: {tenant_id}")
        if status is TenantStatus.PROVISIONING:
            return _deny(TenantErrorCode.TENANT_PROVISIONING, f"tenant provisioning: {tenant_id}")
        return None


__all__ = ["TenantIdentityResolver", "IdentityResolution", "Resolver"]