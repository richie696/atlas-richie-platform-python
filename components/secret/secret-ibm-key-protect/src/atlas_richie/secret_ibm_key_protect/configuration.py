"""IBM Key Protect configuration resolver — auth + endpoint + binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.ibm.IbmKeyProtectProperties`
(SDK 改造后 Java 端没有独立 Configuration 类;Python 端按 R-235
模式拆出独立 resolver)。

校验:

- `region` 非空
- `instance_id` 非空
- `auth_type == BEARER_TOKEN`(其它拒收,`SEC-BOOT-003`)
- `bearer_token` 必填
- `kms_endpoint` 如果设置,必须是 `https://...`
- `kms_key_bindings` logical / physical 非空

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint(R-242 framework 升级新增)。

English
--------
Resolves `IbmKeyProtectProperties` to a
`ResolvedIbmKeyProtectConfiguration`. Capability
fingerprint is included in the configuration hash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from atlas_richie.secret.crypto import capability_fingerprint
from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability
from atlas_richie.secret_ibm_key_protect.properties import (
    AuthType,
    IbmKeyProtectProperties,
)


def _ibm_kms_capability() -> SecretCapability:
    """KMS-only capability for the IBM Key Protect backend.

    Mirrors Java's `Set<SecretCapability>` for
    `IbmKeyProtectSdkSecretTransport`:
    - KEY_WRAP / KEY_UNWRAP (KMS Encrypt / Decrypt)
    - **No** SECRET_READ (Java `read()` throws
      `SEC-CAP-001`)
    - encrypts_at_rest=True (KMS-backed)
    - signs_values=False
    - can_list=False
    - **No** AAD support (IBM Key Protect wrap/unwrap has
      no AAD field)
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
            f"ibm-key-protect: kms_endpoint host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"ibm-key-protect: kms_endpoint must use https:// "
            f"(or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(properties: IbmKeyProtectProperties) -> None:
    if properties.auth_type is not AuthType.BEARER_TOKEN:
        raise SecretConfigurationException(
            f"ibm-key-protect: auth_type must be BEARER_TOKEN; got "
            f"{properties.auth_type!r} (SEC-BOOT-003)",
        )
    if not properties.bearer_token or not properties.bearer_token.strip():
        raise SecretConfigurationException(
            "ibm-key-protect: bearer_token is required for "
            "BEARER_TOKEN auth (SEC-BOOT-003)",
        )


def _validate_secret_mappings(keys: Mapping[str, str]) -> None:
    for logical, physical in keys.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"ibm-key-protect: kms_key_bindings logical name must be "
                f"non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"ibm-key-protect: kms_key_bindings[{logical!r}] physical key "
                f"CRN must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedIbmKeyProtectConfiguration:
    """Immutable result of resolving `IbmKeyProtectProperties`."""

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_ibm_kms_capability)


class IbmKeyProtectConfigurationResolver:
    """Resolve `IbmKeyProtectProperties` to a `ResolvedIbmKeyProtectConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "ibm-key-protect",
    ) -> ResolvedIbmKeyProtectConfiguration:
        self._validate(properties)
        return ResolvedIbmKeyProtectConfiguration(
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
        cap = capability_fingerprint(_ibm_kms_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.instance_id}\n"
            f"{properties.key_ring}\n"
            f"{properties.kms_endpoint or ''}\n"
            f"{bindings_canonical}\n"
            f"{cap}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedIbmKeyProtectConfiguration",
    "IbmKeyProtectConfigurationResolver",
]
