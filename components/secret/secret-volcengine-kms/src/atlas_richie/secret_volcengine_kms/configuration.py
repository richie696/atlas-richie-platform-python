"""Volcengine configuration resolver — region / namespace / binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.volcengine.VolcengineSecretConfiguration`
(SDK 改造后 Java 端没有独立 Configuration 类,逻辑合并到
Transport;Python 端按 R-235 模式拆出独立 resolver)。

校验:

- `region` / `namespace` 必填(Volcengine keyring namespace 强制)
- `access_key_id` / `access_key_secret` 在 ACCESS_KEY 模式下必填
- `kms_key_bindings` logical / physical 非空
- `kms_endpoint` 如果设置,必须是 `https://...`(loopback 仅开发)
- **KMS-only capability**:`can_read=False / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False` (Java SDK transport 同一份契约)
- **旧 REST 配置门禁**:本 wheel 不接 `wire.*` / `tls.*` /
  `proxy.*` 旧配置

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint。

English
--------
Resolves `VolcengineSecretProperties` to a
`ResolvedVolcengineConfiguration`. Capability matrix
matches Java SDK transport: KMS-only, no secret read.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability


def _volcengine_capability() -> SecretCapability:
    """Static capability for the Volcengine backend (mirrors Java
    `Set<SecretCapability>` for `VolcengineSdkSecretTransport`):
    - KMS-only: `can_read=False / can_write=False / can_rotate=False`
    - `KEY_WRAP` / `KEY_UNWRAP` only
    - `encrypts_at_rest=True` (Volcengine KMS encrypts at rest)
    - `signs_values=False`
    - `can_list=False`
    """
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=False,
    )


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    return host.lower() in {"localhost", "127.0.0.1", "::1"}


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        raise SecretConfigurationException(
            f"volcengine: kms_endpoint host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"volcengine: kms_endpoint must use https:// (or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(
    access_key_id: str,
    access_key_secret: str,
    namespace: str,
) -> None:
    if not access_key_id or not access_key_id.strip():
        raise SecretConfigurationException(
            "volcengine: ACCESS_KEY authentication requires access_key_id (SEC-BOOT-003)",
        )
    if not access_key_secret or not access_key_secret.strip():
        raise SecretConfigurationException(
            "volcengine: ACCESS_KEY authentication requires access_key_secret (SEC-BOOT-003)",
        )
    if not namespace or not namespace.strip():
        raise SecretConfigurationException(
            "volcengine: namespace is required (keyring namespace) (SEC-BOOT-003)",
        )


def _validate_key_bindings(bindings: Mapping[str, str]) -> None:
    for logical, physical in bindings.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"volcengine: kms_key_bindings logical key must be non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"volcengine: kms_key_bindings physical KeyName must be non-blank "
                f"for logical {logical!r}",
            )


@dataclass(frozen=True, slots=True)
class ResolvedVolcengineConfiguration:
    """Immutable result of resolving `VolcengineSecretProperties`."""

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_volcengine_capability)


class VolcengineConfigurationResolver:
    """Resolve `VolcengineSecretProperties` to a `ResolvedVolcengineConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "volcengine",
    ) -> ResolvedVolcengineConfiguration:
        self._validate(properties)
        return ResolvedVolcengineConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        if properties.kms_endpoint is not None and properties.kms_endpoint.strip():
            _validate_endpoint(properties.kms_endpoint)
        _validate_auth(
            properties.access_key_id,
            properties.access_key_secret,
            properties.namespace,
        )
        _validate_key_bindings(properties.kms_key_bindings)

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "object",
    ) -> str:
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(properties.kms_key_bindings.items())
        )
        cap = capability_fingerprint(_volcengine_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.namespace}\n"
            f"{properties.kms_endpoint or ''}\n"
            f"{properties.access_key_id}\n"
            f"{bool(properties.access_key_secret)}\n"
            f"{bool(properties.security_token)}\n"
            f"{bindings_canonical}\n"
            f"{cap}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedVolcengineConfiguration",
    "VolcengineConfigurationResolver",
]
