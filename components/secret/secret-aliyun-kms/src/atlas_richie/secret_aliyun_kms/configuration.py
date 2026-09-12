"""Aliyun configuration resolver — path safety + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.aliyun.AliyunSecretConfigurationResolver`。

职责:

1. **path safety 校验**:`secrets_manager_path_prefix` 不允许
   `..` / 开头 `/` / 结尾 `/`(对位 Java `safeLogicalName` +
   `safePath`)
2. **endpoint 校验**:必须 `https://...`(loopback `http://` 仅开发用);
   `.cryptoservice.kms.aliyuncs.com` 专有 endpoint 强制要求 `ca_file`
3. **key binding / secret mapping 校验**:logical key 合法、physical
   key 非空、secret_name 非空
4. **configuration_hash**:SHA-256 over canonical fields,用于 session
   reuse detection(对位 Java `hash`)

**没有** writer / deletable 概念(Java 端 `AliyunSecretClient` 也不
实现 writer);但有 `SECRET_LIST`(对位 Java `SECRET_VERSIONING`)—
Aliyun SDK 不暴露 list API,所以 capability 里 `can_list=False`。

English
--------
Resolves `AliyunSecretProperties` to `ResolvedAliyunConfiguration`.
Mirrors Java `AliyunSecretConfigurationResolver`. Path safety
+ endpoint + binding + mapping validation, SHA-256
configuration hash. No `SecretWriter` / `SecretDeletable`
SPI (mirrors Java's read-only + wrap-only surface).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

if TYPE_CHECKING:
    from atlas_richie.secret_aliyun_kms.properties import AliyunSecretProperties


_logger = logging.getLogger("atlas_richie.secret_aliyun_kms.configuration")


def _aliyun_capability() -> SecretCapability:
    """Static capability for the Aliyun backend.

    Mirrors Java `Set<SecretCapability>` for `AliyunSecretClient`:
    - `SECRET_READ` (SM `GetSecretValue`)
    - `SECRET_VERSIONING` (SM `VersionId` + `VersionStage`)
    - `KEY_WRAP` / `KEY_UNWRAP` (KMS `Encrypt` / `Decrypt`)
    - `encrypts_at_rest=True` (SM encrypts at rest by default
      when backed by KMS)
    - `signs_values=False` (no asymmetric sign support here)
    - `can_list=False` (Aliyun SDK has no list API in the 20160120
      version, matching Java's omission)
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
    lowered = host.lower()
    return lowered in {"localhost", "127.0.0.1", "::1"}


def _validate_endpoint(endpoint: str | None) -> None:
    """Mirror Java `AliyunSecretConfigurationResolver.validateEndpoint`."""
    if endpoint is None:
        return
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        raise SecretConfigurationException(
            f"aliyun: endpoint host is required: {endpoint!r}",
        )
    # `urlparse` exposes userinfo as a private attribute in
    # Python 3.12+; read via `netloc` instead.
    netloc = parsed.netloc
    if "@" in netloc or parsed.query or parsed.fragment:
        raise SecretConfigurationException(
            f"aliyun: endpoint must not contain user-info / query / fragment: {endpoint!r}",
        )
    if parsed.path and parsed.path != "/":
        raise SecretConfigurationException(
            f"aliyun: endpoint path must be empty or '/': {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme != "https" and not (scheme == "http" and _is_loopback(parsed.hostname)):
        raise SecretConfigurationException(
            f"aliyun: endpoint must use https; http is only allowed for "
            f"loopback development: {endpoint!r}",
        )


def _validate_path_prefix(prefix: str) -> None:
    if not prefix:
        return
    if ".." in prefix or "://" in prefix or prefix.startswith("/") or prefix.endswith("/"):
        raise SecretConfigurationException(
            f"aliyun: secrets_manager_path_prefix is invalid (no '..', "
            f"'://', leading or trailing '/' allowed): {prefix!r}",
        )


def _validate_key_bindings(bindings: dict[str, str]) -> None:
    for logical, physical in bindings.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"aliyun: kms_key_bindings logical key must be non-blank: {logical!r}",
            )
        if ".." in logical or "://" in logical or logical.startswith("/"):
            raise SecretConfigurationException(
                f"aliyun: kms_key_bindings logical key is invalid: {logical!r}",
            )
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"aliyun: kms_key_bindings physical key id must be non-blank "
                f"for logical {logical!r}",
            )


def _validate_secret_mappings(
    secrets: dict[str, "AliyunSecretMapping"],
) -> None:
    for logical, mapping in secrets.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"aliyun: secrets logical name must be non-blank: {logical!r}",
            )
        if mapping is None:
            raise SecretConfigurationException(
                f"aliyun: secrets[{logical!r}] mapping must not be null",
            )
        if not mapping.secret_name or not mapping.secret_name.strip():
            raise SecretConfigurationException(
                f"aliyun: secrets[{logical!r}] secret_name must be non-blank",
            )
        if mapping.field is not None and (
            ".." in mapping.field or "://" in mapping.field or mapping.field.startswith("/")
        ):
            raise SecretConfigurationException(
                f"aliyun: secrets[{logical!r}] field is invalid: {mapping.field!r}",
            )


@dataclass(frozen=True, slots=True)
class ResolvedAliyunConfiguration:
    """Immutable result of resolving `AliyunSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"aliyun-main"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields; callers use this to detect when a session
            was created from an identical config and can be
            safely reused.
        capability: Static capability of the Aliyun backend.
    """

    provider_id: str
    properties: "AliyunSecretProperties"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_aliyun_capability)


class AliyunConfigurationResolver:
    """Resolve `AliyunSecretProperties` to a `ResolvedAliyunConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "AliyunSecretProperties",
        *,
        provider_id: str = "aliyun-main",
    ) -> ResolvedAliyunConfiguration:
        self._validate(properties)
        return ResolvedAliyunConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "AliyunSecretProperties") -> None:
        # region already enforced by pydantic validator.
        _validate_endpoint(properties.endpoint)
        if (
            properties.endpoint is not None
            and ".cryptoservice.kms.aliyuncs.com" in properties.endpoint.lower()
            and not properties.ca_file
        ):
            raise SecretConfigurationException(
                "aliyun: dedicated KMS endpoint "
                "(*.cryptoservice.kms.aliyuncs.com) requires ca_file",
            )
        _validate_path_prefix(properties.secrets_manager_path_prefix)
        _validate_key_bindings(properties.kms_key_bindings)
        _validate_secret_mappings(properties.secrets)

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "AliyunSecretProperties",
    ) -> str:
        bindings = properties.kms_key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        secret_keys = "\n".join(sorted((properties.secrets or {}).keys()))
        canonical = (
            f"{provider_id}\n"
            f"{properties.region}\n"
            f"{properties.endpoint or ''}\n"
            f"{properties.ca_file or ''}\n"
            f"{properties.secrets_manager_path_prefix}\n"
            f"{bindings_canonical}\n"
            f"{secret_keys}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedAliyunConfiguration",
    "AliyunConfigurationResolver",
]
