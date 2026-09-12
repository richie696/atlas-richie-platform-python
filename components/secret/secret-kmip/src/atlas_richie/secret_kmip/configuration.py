"""KMIP configuration resolver — endpoint + binding 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.KmipSecretConfiguration`
(Lombok-style 紧凑写法,翻译为 Python dataclass + 模块级函数)。

校验:

- **endpoint**:scheme 必须是 `kmips` / `https` / loopback `http`
- **key binding**:`logical` 路径不能含 `..` / `://` / `/`,`physical`
  UniqueID 非空
- **protocol version**:`major` ∈ {1, 2},`minor` ∈ {0..9}
- **TLS material**:trust_store / key_store 路径不为空(若设置)

**configuration_hash**:SHA-256 over canonical fields,用于
session reuse detection(对位 Java `hash`)。

English
--------
Resolves `KmipSecretProperties` to a
`ResolvedKmipConfiguration`. Mirrors Java
`KmipSecretConfiguration.validate` + `hash`. Endpoints
must use `kmips://` / `https://` (or `http://localhost` /
`http://127.0.0.1` for dev). Logical key names are
path-safe. SHA-256 configuration hash enables session
reuse detection.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability


def _kmip_capability() -> SecretCapability:
    """Static capability for the KMIP backend (mirrors Java
    `Set<SecretCapability>` for `KmipSecretClient`):
    - `KEY_WRAP` / `KEY_UNWRAP` (KMIP Encrypt / Decrypt)
    - `encrypts_at_rest=True` (KMIP server stores keys encrypted)
    - `signs_values=False` (no Sign operation exposed)
    - `can_read=False` / `can_list=False` / `can_write=False`
      (KMIP is a key-management protocol, not a secret store)
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
    """Mirror Java `KmipSecretConfiguration.validate` endpoint check.

    Allowed: `kmips://...` (production), `https://...` (production),
    `http://localhost|127.0.0.1|[::1]:...` (dev only). No
    user-info, query, or fragment in the URL.
    """
    parsed = urlparse(endpoint)
    if "@" in parsed.netloc or parsed.query or parsed.fragment:
        raise SecretConfigurationException(
            f"kmip: endpoint must not contain user-info / query / fragment: {endpoint!r}",
        )
    if not parsed.hostname:
        raise SecretConfigurationException(
            f"kmip: endpoint host is required: {endpoint!r}",
        )
    scheme = (parsed.scheme or "").lower()
    if scheme == "kmips" or scheme == "https":
        return
    if scheme == "http" and _is_loopback(parsed.hostname):
        return
    raise SecretConfigurationException(
        f"kmip: endpoint must use kmips:// or https:// (loopback http allowed "
        f"only for dev): {endpoint!r}",
    )


def _validate_path(value: str, label: str) -> None:
    if not value or not value.strip():
        raise SecretConfigurationException(
            f"kmip: {label} must be non-blank",
        )
    if ".." in value or "://" in value or value.startswith("/") or value.endswith("/"):
        raise SecretConfigurationException(
            f"kmip: {label} is invalid (no '..', '://', leading or trailing '/'): {value!r}",
        )


def _validate_key_bindings(bindings: Mapping[str, str]) -> None:
    for logical, physical in bindings.items():
        _validate_path(logical, "kms logical key")
        if not physical or not physical.strip():
            raise SecretConfigurationException(
                f"kmip: kms_key_bindings physical UniqueID must be non-blank "
                f"for logical {logical!r}",
            )


@dataclass(frozen=True, slots=True)
class ResolvedKmipConfiguration:
    """Immutable result of resolving `KmipSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"kmip"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields; callers use this to detect when a session
            was created from an identical config and can be
            safely reused.
        capability: Static capability of the KMIP backend.
    """

    provider_id: str
    properties: "object"  # forward-ref to KmipSecretProperties
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_kmip_capability)


class KmipConfigurationResolver:
    """Resolve `KmipSecretProperties` to a `ResolvedKmipConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "kmip",
    ) -> ResolvedKmipConfiguration:
        self._validate(properties)
        return ResolvedKmipConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        # endpoint already enforced by pydantic validator.
        _validate_endpoint(properties.endpoint)
        if properties.protocol_major < 1 or properties.protocol_major > 2:
            raise SecretConfigurationException(
                f"kmip: protocol_major is invalid: {properties.protocol_major}",
            )
        if properties.protocol_minor < 0 or properties.protocol_minor > 9:
            raise SecretConfigurationException(
                f"kmip: protocol_minor is invalid: {properties.protocol_minor}",
            )
        _validate_key_bindings(properties.key_bindings)
        if properties.trust_store is not None and properties.trust_store.strip():
            _validate_path(properties.trust_store, "trust_store")
        if properties.key_store is not None and properties.key_store.strip():
            _validate_path(properties.key_store, "key_store")

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "object",
    ) -> str:
        bindings = properties.key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.endpoint}\n"
            f"{properties.trust_store or ''}\n"
            f"{properties.key_store or ''}\n"
            f"{properties.protocol_major}.{properties.protocol_minor}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedKmipConfiguration",
    "KmipConfigurationResolver",
]
