"""AWS configuration resolver — path safety + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.aws.AwsSecretConfigurationResolver`。

职责:

1. **path safety 校验**:`secrets_manager_path_prefix` 不允许
   `..` / 开头 `/`(对位 Java `safeLogicalName`)
2. **capability 固定**:AWS backend 静态声明
   `can_read=True, can_write=False, can_rotate=True, can_list=True,
   encrypts_at_rest=True, signs_values=False, cacheable=True`
   (对位 Java `Set<SecretCapability>` 6 个 capability)
3. **configuration_hash**:SHA-256 over canonical fields,用于
   session reuse detection

AWS 跟 Vault 不同:**没有 writer / deletable 概念**(Java 端
`AwsSecretClient` 也不实现 writer),所以 capability 里
`can_write=False`。但 `can_list=True`(SM 有 `list_secrets`)。

English
--------
Resolves `AwsSecretProperties` to `ResolvedAwsConfiguration`.
Mirrors Java `AwsSecretConfigurationResolver`. Path safety
check on the Secrets Manager path prefix, static
`SecretCapability` declaration, SHA-256 configuration hash.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

if TYPE_CHECKING:
    from atlas_richie.secret_aws_kms.properties import AwsSecretProperties


def _safe_path(value: str, label: str) -> None:
    """Validate a logical-name path: no `..`, no `://`, no
    leading or trailing `/`. Mirrors the vault wheel's
    internal validator; inlined here so `secret-aws-kms` does
    not have a runtime dependency on `secret-vault`.
    """
    if not value or ".." in value or "://" in value or value.startswith("/") or value.endswith("/"):
        raise SecretConfigurationException(
            f"aws: {label} is invalid (no '..', '://', leading or trailing '/' allowed): {value!r}",
        )

_logger = logging.getLogger("atlas_richie.secret_aws_kms.configuration")


def _aws_capability() -> SecretCapability:
    """Static capability for the AWS backend.

    Mirrors Java `Set<SecretCapability>` for
    `AwsSecretClient`:
    - `SECRET_READ` / `SECRET_VERSIONING` (SM read + version)
    - `SECRET_LIST` (SM `list_secrets` — Java side has this)
    - `KEY_WRAP` / `KEY_UNWRAP` (KMS GenerateDataKey / Decrypt)
    - `SIGN` / `VERIFY` (KMS Sign / Verify)
    - `encrypts_at_rest=True` (SM encrypts at rest by default
      when backed by KMS)
    """
    return SecretCapability(
        can_read=True,
        can_write=False,  # 1:1 with Java: no SecretWriter SPI
        can_rotate=True,
        can_list=True,    # SM list_secrets exists
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


@dataclass(frozen=True, slots=True)
class ResolvedAwsConfiguration:
    """Immutable result of resolving `AwsSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"aws-main"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields; callers use this to detect when a session
            was created from an identical config and can be
            safely reused.
        capability: Static capability of the AWS backend.
    """

    provider_id: str
    properties: "AwsSecretProperties"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_aws_capability)


class AwsConfigurationResolver:
    """Resolve `AwsSecretProperties` to a `ResolvedAwsConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "AwsSecretProperties",
        *,
        provider_id: str = "aws-main",
    ) -> ResolvedAwsConfiguration:
        self._validate_paths(properties)
        return ResolvedAwsConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate_paths(properties: "AwsSecretProperties") -> None:
        # secrets_manager_path_prefix is a logical name space; same
        # rules as Vault's `namespace`.
        if properties.secrets_manager_path_prefix:
            _safe_path(properties.secrets_manager_path_prefix, "secrets_manager_path_prefix")

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "AwsSecretProperties",
    ) -> str:
        bindings = properties.kms_key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.auth_type.value}\n"
            f"{properties.profile_name or ''}\n"
            f"{properties.kms_signing_algorithm}\n"
            f"{properties.endpoint_kms or ''}\n"
            f"{properties.endpoint_sm or ''}\n"
            f"{properties.secrets_manager_path_prefix}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedAwsConfiguration",
    "AwsConfigurationResolver",
]
