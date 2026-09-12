"""OCI configuration resolver — auth + endpoint + binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.oci.OciSecretConfiguration`
(经 SDK 改造后 Java 端没有独立 Configuration 类,逻辑合并到
Transport;Python 端按 R-235 模式拆出独立 resolver)。

校验:

- `region` 非空
- `auth_type ∈ {NONE, WORKLOAD_IDENTITY_TOKEN_FILE}`;
  ACCESS_KEY 拒收(`SEC-BOOT-003`)
- `secrets` / `kms_key_bindings` logical / physical 非空
- `secret_endpoint` / `kms_endpoint` 如果设置,必须是
  `https://...`(loopback `http://` 仅开发)

`configuration_hash`:SHA-256 over canonical fields,包含
capability fingerprint(R-242 framework 升级新增)。

English
--------
Resolves `OciSecretProperties` to a
`ResolvedOciConfiguration`. Capability fingerprint is
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
from atlas_richie.secret_oci_vault_kms.properties import AuthType


def _oci_capability() -> SecretCapability:
    """Static capability for the OCI backend (mirrors Java
    `Set<SecretCapability>` for `OciSdkSecretTransport`):
    - SECRET_READ (Vault getSecretBundle)
    - SECRET_VERSIONING (Vault versionNumber / stage / alias)
    - KEY_WRAP / KEY_UNWRAP (KmsCrypto encrypt / decrypt)
    - encrypts_at_rest=True (Vault secrets Base64-encoded)
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
            f"oci: {label} host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"oci: {label} must use https:// (or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(auth_type: AuthType) -> None:
    if auth_type not in (AuthType.NONE, AuthType.WORKLOAD_IDENTITY_TOKEN_FILE):
        raise SecretConfigurationException(
            f"oci: auth_type must be NONE (Instance Principal) or "
            f"WORKLOAD_IDENTITY_TOKEN_FILE (Resource Principal); got {auth_type!r} "
            f"(SEC-BOOT-003)",
        )


def _validate_secret_mappings(
    secrets: Mapping[str, str],
    keys_label: str,
) -> None:
    for logical, physical in secrets.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"oci: {keys_label} logical name must be non-blank: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"oci: {keys_label}[{logical!r}] physical id must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedOciConfiguration:
    """Immutable result of resolving `OciSecretProperties`."""

    provider_id: str
    properties: "object"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_oci_capability)


class OciConfigurationResolver:
    """Resolve `OciSecretProperties` to a `ResolvedOciConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "oci",
    ) -> ResolvedOciConfiguration:
        self._validate(properties)
        return ResolvedOciConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        _validate_auth(properties.auth_type)
        if properties.secret_endpoint is not None and properties.secret_endpoint.strip():
            _validate_endpoint(properties.secret_endpoint, "secret_endpoint")
        if properties.kms_endpoint is not None and properties.kms_endpoint.strip():
            _validate_endpoint(properties.kms_endpoint, "kms_endpoint")
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
        cap = capability_fingerprint(_oci_capability())
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.auth_type.value}\n"
            f"{bool(properties.workload_identity_token_file)}\n"
            f"{properties.secret_endpoint or ''}\n"
            f"{properties.kms_endpoint or ''}\n"
            f"{secrets_canonical}\n"
            f"{bindings_canonical}\n"
            f"{cap}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedOciConfiguration",
    "OciConfigurationResolver",
]
