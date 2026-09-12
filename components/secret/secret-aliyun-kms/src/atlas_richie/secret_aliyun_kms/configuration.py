"""`AliyunConfigurationResolver` — provider_id + SHA-256 hash + path safety 校验。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretConfigurationResolver`。
职责:

1. **provider_id 解析**:从 `SecretBootstrapContext`-shape 的输入解析
   `(provider_id, configuration_prefix)` 元组;Python 端没 Spring
   `Environment`,所以 caller 直接传 tuple 给 `resolve(...)` 方法。
2. **validate(properties)**:enforce
   - `region` 非空(对位 Java `BlankRegionException` → `SEC-BOOT-003`)
   - `endpoint` 必须 `https://...`(loopback HTTP 开发场景除外;
     对位 Java `EndpointSchemeException`)
   - `endpoint` host 含 `.cryptoservice.kms.aliyuncs.com` ⇒
     `ca_file` 必填(对位 Java `MissingCaFileException`)
   - `secrets_manager_path_prefix` 不可 `..` / `://` / 头尾 `/`
   - `kms_key_bindings` keys safe logical,values 非空
   - `secrets` mappings 不可空值,`secret_name` 非空,`field`(若设置)
     safe logical
3. **configuration_hash**:SHA-256 over
   `provider_id + region + endpoint + ca_file + path_prefix +
   sorted_key_bindings + sorted_secret_keys`,64-char hex(对位 Java
   `ConfigurationHash` SHA-256 + canonical field ordering)。

`ResolvedAliyunConfiguration` 是 frozen dataclass,持有
`provider_id` / `properties` / `configuration_hash` /
`capability`,与其它 backend wheel(`secret-aws-kms` /
`secret-azure-keyvault`)保持形状一致。

English
--------
Resolves `AliyunSecretProperties` to `ResolvedAliyunConfiguration`.
Mirrors Java `AliyunSecretConfigurationResolver`. Path-safety
validation, dedicated-KMS CA bundle enforcement, SHA-256
configuration hash. The resolver's only public method is
`resolve(...)`; validation is split into `_validate(properties)` so
the test surface can exercise it directly.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

from atlas_richie.secret_aliyun_kms.properties import (
    AliyunSecretMapping,
    AliyunSecretProperties,
)

if TYPE_CHECKING:
    pass

_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.configuration")

# Mirrors Java's `safeLogicalName` regex: ASCII letters / digits /
# `-` / `_` / `.`, no whitespace, no path separators. We deliberately
# do NOT allow `/` (path prefix is responsible for slashes) and we
# reject `..` upstream.
_SAFE_LOGICAL = re.compile(r"^[A-Za-z0-9._-]+$")

# Hostnames that signal a dedicated KMS instance (VPC private link).
# Mirrors Java's check in `AliyunClientFactory.create(...)`.
_DEDICATED_KMS_HOST_SUFFIX = ".cryptoservice.kms.aliyuncs.com"

# Loopback HTTP schemes that are accepted in dev / CI but never in prod.
_LOOPBACK_SCHEMES = frozenset({"http://localhost", "http://127.0.0.1", "http://[::1]"})

# Stable, non-Protocol exports re-exposed for `from configuration import X`
# convenience.
_ = (field,)


def _aliyun_capability() -> SecretCapability:
    """Static capability for the Alibaba Cloud backend.

    Mirrors Java `Set<SecretCapability>` for `AliyunSecretClient`:
    - `SECRET_READ` / `SECRET_VERSIONING` (Secrets Manager get / version)
    - `KEY_WRAP` / `KEY_UNWRAP` (KMS symmetric Encrypt / Decrypt)
    - `can_list=False` (Secrets Manager has `ListSecrets` but Java
      explicitly does not implement `SecretListable` for this backend;
      Python mirrors that narrower surface)
    - `encrypts_at_rest=True` (Secrets Manager stores ciphertext
      server-side; KMS never exposes the master key)
    - `signs_values=False` (Aliyun KMS has no `Sign` / `Verify` on the
      symmetric endpoint used here)
    """
    return SecretCapability(
        can_read=True,
        can_write=False,  # 1:1 with Java: no SecretWriter SPI
        can_rotate=True,  # Secrets Manager version stage
        can_list=False,  # Mirrors Java's narrower scope
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


@dataclass(frozen=True, slots=True)
class ResolvedAliyunConfiguration:
    """Immutable result of resolving `AliyunSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"aliyun-default"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical fields;
            callers use this to detect when a session was created
            from an identical config and can be safely reused.
        capability: Static capability of the Alibaba Cloud backend.
    """

    provider_id: str
    properties: AliyunSecretProperties
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_aliyun_capability)


class AliyunConfigurationResolver:
    """Resolve `AliyunSecretProperties` to a `ResolvedAliyunConfiguration`.

    The single public entry point is `resolve(properties, *,
    provider_id, configuration_prefix)`. Validation is delegated
    to the private `_validate(properties)` so unit tests can exercise
    it without the full resolver plumbing.
    """

    __slots__ = ()

    def resolve(
        self,
        properties: AliyunSecretProperties,
        *,
        provider_id: str = "aliyun-default",
        configuration_prefix: str = "",
    ) -> ResolvedAliyunConfiguration:
        """Validate, hash, and wrap `properties`.

        Args:
            properties: The pydantic-settings-validated properties.
            provider_id: Stable identifier for the resolved
                provider. Defaults to ``"aliyun-default"``; factory
                callers typically pass a region-suffixed value.
            configuration_prefix: Reserved for framework symmetry with
                the Java `SecretBootstrapContext.environment` field.
                Currently unused; the prefix is captured via
                `properties.secrets_manager_path_prefix` instead.
        """
        _ = configuration_prefix  # reserved for future use
        self._validate(properties)
        configuration_hash = self._configuration_hash(provider_id, properties)
        _logger.debug(
            "aliyun: resolved configuration provider_id=%r hash=%s",
            provider_id,
            configuration_hash,
        )
        return ResolvedAliyunConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=configuration_hash,
        )

    # --- Validation ----------------------------------------------------

    @staticmethod
    def _validate(properties: AliyunSecretProperties) -> None:
        """Run all `AliyunSecretProperties` invariants.

        Order matters: the most fundamental checks (region, endpoint
        scheme) come first so a misconfigured environment fails
        fast with a clear message rather than burying the error
        under a list of path-prefix problems.
        """
        AliyunConfigurationResolver._validate_region(properties.region)
        AliyunConfigurationResolver._validate_endpoint(properties)
        AliyunConfigurationResolver._validate_path_prefix(properties.secrets_manager_path_prefix)
        AliyunConfigurationResolver._validate_kms_key_bindings(properties.kms_key_bindings)
        AliyunConfigurationResolver._validate_secret_mappings(properties.secrets)

    @staticmethod
    def _validate_region(region: str) -> None:
        if not region or not region.strip():
            raise SecretConfigurationException(
                "SEC-BOOT-003 aliyun: region is required and must be non-blank",
            )

    @staticmethod
    def _validate_endpoint(properties: AliyunSecretProperties) -> None:
        endpoint = properties.endpoint
        if not endpoint:
            return
        if endpoint in _LOOPBACK_SCHEMES:
            # Loopback HTTP is allowed only in dev / CI. We deliberately
            # do NOT check for the dedicated-KMS host here because
            # loopback is never a dedicated KMS endpoint.
            return
        try:
            parsed = urlparse(endpoint)
        except ValueError as error:
            raise SecretConfigurationException(
                f"SEC-BOOT-003 aliyun: endpoint is not a valid URL: {endpoint!r}",
            ) from error
        if parsed.scheme != "https":
            raise SecretConfigurationException(
                f"SEC-BOOT-003 aliyun: endpoint must use https:// (or http://localhost for dev): {endpoint!r}",
            )
        host = (parsed.hostname or "").lower()
        if host.endswith(_DEDICATED_KMS_HOST_SUFFIX) and not properties.ca_file:
            raise SecretConfigurationException(
                f"SEC-BOOT-003 aliyun: dedicated KMS endpoint {host!r} requires ca_file",
            )

    @staticmethod
    def _validate_path_prefix(prefix: str | None) -> None:
        if prefix is None:
            return
        if not prefix:
            raise SecretConfigurationException(
                "SEC-BOOT-003 aliyun: secrets_manager_path_prefix must be non-blank when set",
            )
        if ".." in prefix or "://" in prefix or prefix.startswith("/") or prefix.endswith("/"):
            raise SecretConfigurationException(
                f"SEC-BOOT-003 aliyun: secrets_manager_path_prefix is invalid "
                f"(no '..', '://', leading or trailing '/' allowed): {prefix!r}",
            )

    @staticmethod
    def _validate_kms_key_bindings(bindings: Mapping[str, str]) -> None:
        for logical, physical in bindings.items():
            if not _SAFE_LOGICAL.fullmatch(logical):
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: kms_key_bindings key {logical!r} is not a safe logical name",
                )
            if not physical or not physical.strip():
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: kms_key_bindings[{logical!r}] has a blank physical key id",
                )

    @staticmethod
    def _validate_secret_mappings(secrets: Mapping[str, AliyunSecretMapping]) -> None:
        for logical, mapping in secrets.items():
            if mapping is None:
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: secrets[{logical!r}] mapping is null",
                )
            if not _SAFE_LOGICAL.fullmatch(logical):
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: secrets key {logical!r} is not a safe logical name",
                )
            if not mapping.secret_name or not mapping.secret_name.strip():
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: secrets[{logical!r}].secret_name must be non-blank",
                )
            if mapping.field is not None and not _SAFE_LOGICAL.fullmatch(mapping.field):
                raise SecretConfigurationException(
                    f"SEC-BOOT-003 aliyun: secrets[{logical!r}].field {mapping.field!r} is not a safe logical name",
                )

    # --- Hash -----------------------------------------------------------

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: AliyunSecretProperties,
    ) -> str:
        """Return a 64-char hex SHA-256 over canonical configuration fields.

        The canonical input is a `\n`-separated concatenation of:

        - `provider_id`
        - `region`
        - `endpoint` (empty string when unset)
        - `ca_file` (empty string when unset)
        - `secrets_manager_path_prefix` (empty string when unset)
        - sorted `kms_key_bindings` rendered as `logical=physical` lines
        - sorted `secrets` keys (the mapping values are not part of the
          hash because they may contain a JSON `field` selector that
          does not affect the security boundary)

        All sorting uses `sorted(...)` for cross-process determinism
        (Python's sort is stable + locale-independent for string keys).
        """
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(properties.kms_key_bindings.items())
        )
        secret_keys_canonical = "\n".join(sorted(properties.secrets.keys()))
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.endpoint or ''}\n"
            f"{properties.ca_file or ''}\n"
            f"{properties.secrets_manager_path_prefix or ''}\n"
            f"{bindings_canonical}\n"
            f"{secret_keys_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedAliyunConfiguration",
    "AliyunConfigurationResolver",
]
