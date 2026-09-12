"""Vault configuration resolver — 把 `VaultSecretProperties` 提升为不可变启动视图。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultSecretConfigurationResolver`。

职责:

1. **path safety 校验**:mount / runtime prefix / secret path / transit
   key binding 不允许 `..` / `://` / 开头 `/` / 结尾 `/`(对位 Java
   `safePath` + `safeLogicalName`)。这些约束防止 `path traversal` 或
   `http://` 注入。
2. **capability 固定**:Vault backend 静态声明
   `can_read=True, can_write=True, can_rotate=True, can_list=False,
   encrypts_at_rest=True, signs_values=False, cacheable=True`
   (对位 Java `Set<SecretCapability>` 中 6 个 capability)。
3. **configuration_hash**:SHA-256 over canonical fields,用于
   `SecretProviderDescriptor` 鉴别同一份 resolved config 是否复用
   session(reuse detection)。

**注意**:本 wheel 的 auth / KV / Transit 字段已由 `VaultSecretProperties`
的 `model_validator(mode="after")` 校验,resolver 只做"path safety" +
"hash 构造"。如果将来需要重做 BootstrapSecretProperties 的 active-provider
逻辑,可以扩展为接 `provider_id` 参数。

English
--------
Resolves `VaultSecretProperties` into an immutable
`ResolvedVaultConfiguration`. Mirrors Java
`VaultSecretConfigurationResolver`. Validates path safety (no
`..`, no `://`, no leading/trailing `/`), declares the static
`SecretCapability`, and computes a SHA-256 configuration hash for
session-reuse detection.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret_vault.properties import VaultSecretProperties

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_vault.configuration")


def _vault_capability() -> SecretCapability:
    """Static capability for the Vault backend.

    Mirrors Java `Set<SecretCapability>`:
    - `SECRET_READ` / `SECRET_VERSIONING` (KV v2 读 + 版本化)
    - `KEY_WRAP` / `KEY_UNWRAP` (Transit encrypt/decrypt)
    - `SIGN` / `VERIFY` (Transit sign/verify)
    `encrypts_at_rest=True` because Vault persists ciphertext (we
    don't add a local envelope layer here; that's secret-redis's
    role).
    """
    return SecretCapability(
        can_read=True,
        can_write=True,
        can_rotate=True,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


@dataclass(frozen=True, slots=True)
class ResolvedVaultConfiguration:
    """Immutable result of resolving `VaultSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"vault-main"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields; callers use this to detect when a session
            was created from an identical config and can be
            safely reused.
        capability: Static capability of the Vault backend.
    """

    provider_id: str
    properties: VaultSecretProperties
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_vault_capability)


class VaultConfigurationResolver:
    """Resolve `VaultSecretProperties` to a `ResolvedVaultConfiguration`.

    Path safety is enforced here even though pydantic covers most
    fields; the resolver is the single point where a KV mount /
    Transit mount / logical-key binding can be rejected for
    security reasons (path traversal, scheme injection).
    """

    __slots__ = ()

    def resolve(
        self,
        properties: VaultSecretProperties,
        *,
        provider_id: str = "vault-main",
    ) -> ResolvedVaultConfiguration:
        self._validate_paths(properties)
        return ResolvedVaultConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate_paths(properties: VaultSecretProperties) -> None:
        _safe_path(properties.kv_mount, "kv_mount")
        _safe_path(properties.transit_mount, "transit_mount")
        _safe_path(properties.namespace, "namespace")
        if properties.kubernetes_role is not None:
            _safe_logical_name(properties.kubernetes_role, "kubernetes_role")
        if properties.approle_role_id is not None:
            _safe_logical_name(properties.approle_role_id, "approle_role_id")

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: VaultSecretProperties,
    ) -> str:
        """SHA-256 hex over canonical fields, mirroring Java.

        Java includes authentication paths and several key
        bindings. We collapse to the essentials (URL / namespace /
        auth type / mounts / key bindings-equivalent) so the hash
        changes when the deployment-relevant config changes.
        """
        bindings = properties.transit_key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.url}\n"
            f"{properties.namespace}\n"
            f"{properties.auth_type.value}\n"
            f"{properties.kv_mount}\n"
            f"{properties.transit_mount}\n"
            f"{properties.kubernetes_role or ''}\n"
            f"{properties.kubernetes_mount_point}\n"
            f"{properties.approle_role_id or ''}\n"
            f"{properties.approle_mount_point}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_path(value: str, label: str) -> None:
    if not value or ".." in value or "://" in value or value.startswith("/") or value.endswith("/"):
        raise SecretConfigurationException(
            f"vault: {label} is invalid (no '..', '://', leading or trailing '/' allowed): {value!r}",
        )


def _safe_logical_name(value: str, label: str) -> None:
    if not value or ".." in value or "://" in value or value.startswith("/"):
        raise SecretConfigurationException(
            f"vault: {label} is invalid: {value!r}",
        )


__all__ = [
    "ResolvedVaultConfiguration",
    "VaultConfigurationResolver",
]
