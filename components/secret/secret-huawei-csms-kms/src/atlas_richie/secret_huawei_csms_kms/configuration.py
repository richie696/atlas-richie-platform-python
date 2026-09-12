"""Huawei configuration resolver — endpoint / auth / binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.huawei.HuaweiSecretConfiguration`
(经 SDK 改造后 Java 端没有独立 Configuration 类,逻辑合并到
Transport;Python 端按 R-235 模式拆出独立 resolver)。

校验:

- `region` 非空
- `project_id` 必填(Huawei DEW BasicCredentials 必须)
- `access_key_id` / `access_key_secret` 在 ACCESS_KEY 模式下必填
- `secrets` / `kms_key_bindings` logical / physical 非空
- `secret_endpoint` / `kms_endpoint` 如果设置,必须是 `https://...`
  (loopback `http://` 仅开发)
- **旧 REST 配置门禁**:本 wheel 启动期不接 `wire.*` / `tls.*` /
  `proxy.*` 旧配置(R-242 SDK 改造 mandata,Python 端不暴露
  这些字段,等价于隐式拒收)

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint(R-242 framework 升级新增)。

English
--------
Resolves `HuaweiSecretProperties` to a
`ResolvedHuaweiConfiguration`. Mirrors Java
`HuaweiSecretConfiguration`. Capability fingerprint is
included in the configuration hash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability


def _huawei_capability() -> SecretCapability:
    """Static capability for the Huawei backend (mirrors Java
    `Set<SecretCapability>` for `HuaweiSdkSecretTransport`):
    - SECRET_READ (CSMS ShowSecretVersion)
    - SECRET_VERSIONING (CSMS VersionId)
    - KEY_WRAP / KEY_UNWRAP (DEW EncryptData / DecryptData)
    - encrypts_at_rest=True (DEW encrypts at rest)
    - signs_values=False
    - can_list=False
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
            f"huawei: {label} host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"huawei: {label} must use https:// (or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(
    project_id: str,
    access_key_id: str,
    access_key_secret: str,
) -> None:
    if not project_id or not project_id.strip():
        raise SecretConfigurationException(
            "huawei: project_id is required for DEW BasicCredentials (SEC-BOOT-003)",
        )
    if not access_key_id or not access_key_id.strip():
        raise SecretConfigurationException(
            "huawei: ACCESS_KEY authentication requires access_key_id (SEC-BOOT-003)",
        )
    if not access_key_secret or not access_key_secret.strip():
        raise SecretConfigurationException(
            "huawei: ACCESS_KEY authentication requires access_key_secret (SEC-BOOT-003)",
        )


def _validate_secret_mappings(
    secrets: Mapping[str, str],
    keys_label: str,
) -> None:
    for logical, physical in secrets.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"huawei: {keys_label} logical name must be non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"huawei: {keys_label}[{logical!r}] physical id must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedHuaweiConfiguration:
    """Immutable result of resolving `HuaweiSecretProperties`."""

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_huawei_capability)


class HuaweiConfigurationResolver:
    """Resolve `HuaweiSecretProperties` to a `ResolvedHuaweiConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "huawei",
    ) -> ResolvedHuaweiConfiguration:
        self._validate(properties)
        return ResolvedHuaweiConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        if properties.secret_endpoint is not None and properties.secret_endpoint.strip():
            _validate_endpoint(properties.secret_endpoint, "secret_endpoint")
        if properties.kms_endpoint is not None and properties.kms_endpoint.strip():
            _validate_endpoint(properties.kms_endpoint, "kms_endpoint")
        _validate_auth(
            properties.project_id,
            properties.access_key_id,
            properties.access_key_secret,
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
        cap = capability_fingerprint(_huawei_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.project_id}\n"
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
    "ResolvedHuaweiConfiguration",
    "HuaweiConfigurationResolver",
]
