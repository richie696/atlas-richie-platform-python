"""Baidu Cloud KMS configuration resolver — auth + endpoint + binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java
`cn.richie696.component.secret.provider.baidu.BaiduSecretProperties`
(SDK 改造后 Java 端没有独立 Configuration 类;Python 端按
R-235 模式拆出独立 resolver)。

校验:

- `access_key_id` / `access_key_secret` 非空
- `auth_type == ACCESS_KEY`(其它拒收,`SEC-BOOT-003`)
- `kms_endpoint` 如果设置,host 必须非空
- `kms_key_bindings` logical / physical 非空

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint(R-242 framework 升级新增)。

English
--------
Resolves `BaiduSecretProperties` to a
`ResolvedBaiduConfiguration`. Capability fingerprint is
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
from atlas_richie.secret_baidu_kms.properties import (
    AuthType,
    BaiduSecretProperties,
)


def _baidu_kms_capability() -> SecretCapability:
    """KMS-only capability for the Baidu Cloud KMS backend.

    Mirrors Java's `Set<SecretCapability>` for
    `BaiduSdkSecretTransport`:
    - KEY_WRAP / KEY_UNWRAP (KMS Encrypt / Decrypt)
    - **No** SECRET_READ (Java `read()` throws
      `SEC-CAP-001`)
    - encrypts_at_rest=True (KMS-backed)
    - signs_values=False
    - can_list=False
    - **No** AAD support (BCE KMS wrap/unwrap has no AAD
      field)
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


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        raise SecretConfigurationException(
            f"baidu-kms: kms_endpoint host is required: {endpoint!r}",
        )


def _validate_auth(properties: BaiduSecretProperties) -> None:
    if properties.auth_type is not AuthType.ACCESS_KEY:
        raise SecretConfigurationException(
            f"baidu-kms: auth_type must be ACCESS_KEY; got "
            f"{properties.auth_type!r} (SEC-BOOT-003)",
        )
    if not properties.access_key_id or not properties.access_key_id.strip():
        raise SecretConfigurationException(
            "baidu-kms: access_key_id is required for "
            "ACCESS_KEY auth (SEC-BOOT-003)",
        )
    if not properties.access_key_secret or not properties.access_key_secret.strip():
        raise SecretConfigurationException(
            "baidu-kms: access_key_secret is required for "
            "ACCESS_KEY auth (SEC-BOOT-003)",
        )


def _validate_secret_mappings(keys: Mapping[str, str]) -> None:
    for logical, physical in keys.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"baidu-kms: kms_key_bindings logical name must be "
                f"non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"baidu-kms: kms_key_bindings[{logical!r}] physical key id "
                f"must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedBaiduConfiguration:
    """Immutable result of resolving `BaiduSecretProperties`."""

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_baidu_kms_capability)


class BaiduConfigurationResolver:
    """Resolve `BaiduSecretProperties` to a `ResolvedBaiduConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "baidu-kms",
    ) -> ResolvedBaiduConfiguration:
        self._validate(properties)
        return ResolvedBaiduConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        _validate_auth(properties)
        if properties.kms_endpoint is not None and properties.kms_endpoint.strip():
            _validate_endpoint(properties.kms_endpoint)
        _validate_secret_mappings(properties.kms_key_bindings)

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "object",
    ) -> str:
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(properties.kms_key_bindings.items())
        )
        cap = capability_fingerprint(_baidu_kms_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.kms_endpoint}\n"
            f"{properties.access_key_id}\n"
            f"{bindings_canonical}\n"
            f"{cap}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedBaiduConfiguration",
    "BaiduConfigurationResolver",
]
