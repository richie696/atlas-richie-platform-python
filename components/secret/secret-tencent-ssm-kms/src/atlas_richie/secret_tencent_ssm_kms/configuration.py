"""Tencent configuration resolver — endpoint + auth + binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.tencent.TencentSecretConfiguration`
(经 SDK 改造后,Java 端没有独立 Configuration 类,逻辑合并到
Transport;Python 端按 R-235 模式拆出独立 resolver)。

校验:

- `region` 非空
- `access_key_id` / `access_key_secret` 在 `ACCESS_KEY` 模式下必填
- `secrets` / `kms_key_bindings` logical / physical 都非空
- `secret_endpoint` / `kms_endpoint` 如果设置,必须是 `https://...`
  (loopback `http://` 仅开发)
- **旧 REST 配置门禁**:本 wheel 启动期不接 `wire.*` / `tls.*` /
  `proxy.*` 旧配置 — 这些字段的"看似生效、实际被忽略"是 Java
  端明确拒绝的 anti-pattern;Python 端不暴露这些字段,等价于
  隐式拒收

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint(R-242 framework 升级新增,capability
改变会强制重建 session)。

English
--------
Resolves `TencentSecretProperties` to a
`ResolvedTencentConfiguration`. Mirrors Java
`TencentSecretConfiguration`. Includes capability
fingerprint in the configuration hash so a capability
change forces a session rebuild.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability


def _tencent_capability() -> SecretCapability:
    """Static capability for the Tencent backend (mirrors Java
    `Set<SecretCapability>` for `TencentSdkSecretTransport`):
    - SECRET_READ (SSM GetSecretValue)
    - SECRET_VERSIONING (VersionId)
    - KEY_WRAP / KEY_UNWRAP (KMS Encrypt / Decrypt)
    - encrypts_at_rest=True (KMS-encrypted at rest)
    - signs_values=False (no Sign operation)
    - can_list=False (Tencent SDK has no list API)
    """
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    return host.lower() in {"localhost", "127.0.0.1", "::1"}


def _validate_endpoint(endpoint: str, label: str) -> None:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        raise SecretConfigurationException(
            f"tencent: {label} host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"tencent: {label} must use https:// (or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(
    access_key_id: str,
    access_key_secret: str,
    security_token: str | None,
) -> None:
    if not access_key_id or not access_key_id.strip():
        raise SecretConfigurationException(
            "tencent: ACCESS_KEY authentication requires access_key_id (SEC-BOOT-003)",
        )
    if not access_key_secret or not access_key_secret.strip():
        raise SecretConfigurationException(
            "tencent: ACCESS_KEY authentication requires access_key_secret (SEC-BOOT-003)",
        )


def _validate_secret_mappings(
    secrets: Mapping[str, str],
    keys_label: str,
) -> None:
    for logical, physical in secrets.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"tencent: {keys_label} logical name must be non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"tencent: {keys_label}[{logical!r}] physical id must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedTencentConfiguration:
    """Immutable result of resolving `TencentSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"tencent"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields, including capability fingerprint.
        capability: Static capability of the Tencent backend.
    """

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_tencent_capability)


class TencentConfigurationResolver:
    """Resolve `TencentSecretProperties` to a `ResolvedTencentConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "tencent",
    ) -> ResolvedTencentConfiguration:
        self._validate(properties)
        return ResolvedTencentConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        # region already enforced by pydantic validator
        if properties.secret_endpoint is not None and properties.secret_endpoint.strip():
            _validate_endpoint(properties.secret_endpoint, "secret_endpoint")
        if properties.kms_endpoint is not None and properties.kms_endpoint.strip():
            _validate_endpoint(properties.kms_endpoint, "kms_endpoint")
        _validate_auth(
            properties.access_key_id,
            properties.access_key_secret,
            properties.security_token,
        )
        _validate_secret_mappings(properties.secrets, "secrets")
        _validate_secret_mappings(properties.kms_key_bindings, "kms_key_bindings")

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "object",
    ) -> str:
        secrets_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(properties.secrets.items())
        )
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(properties.kms_key_bindings.items())
        )
        cap = capability_fingerprint(_tencent_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.secret_endpoint or ''}\n"
            f"{properties.kms_endpoint or ''}\n"
            f"{properties.access_key_id}\n"
            f"{bool(properties.access_key_secret)}\n"
            f"{bool(properties.security_token)}\n"
            f"{secrets_canonical}\n"
            f"{bindings_canonical}\n"
            f"{cap}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedTencentConfiguration",
    "TencentConfigurationResolver",
]
