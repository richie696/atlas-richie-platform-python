"""Barbican configuration resolver — endpoint + auth 校验 + SHA-256 configuration hash。

中文
----
对位 Java `cn.richie696.component.secret.provider.barbican.BarbicanConfiguration`
(Lombok-style 紧凑写法,翻译为 Python dataclass + 模块级函数)。

校验:

- `endpoint`:`https://...`(loopback `http://` 仅开发)
- **auth**:`TOKEN_FILE` 必须配 `token_file`;`TOKEN` 必须配 `token`
- `secrets`:logical 非空,`id` 非空
- `project_id` 如果有,不能含 `..` / `://`

`configuration_hash`:SHA-256 over canonical fields,用于
session reuse detection。

English
--------
Resolves `BarbicanSecretProperties` to a
`ResolvedBarbicanConfiguration`. Mirrors Java
`BarbicanConfiguration.validate` + `hash`. Auth: TOKEN
must include a non-blank token, TOKEN_FILE must include a
path. SHA-256 configuration hash enables session reuse.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretCapability
from atlas_richie.secret_barbican.properties import (
    AuthType,
    BarbicanSecretMapping,
)


def _barbican_capability() -> SecretCapability:
    """Static capability for the Barbican backend (mirrors Java
    `Set<SecretCapability>` for `BarbicanSecretClient`):
    - `SECRET_READ` / `SECRET_VERSIONING` (Barbican v1 API)
    - `can_write=False` / `can_rotate=False` (read-only)
    - `can_list=False` (Barbican list API not used)
    - `encrypts_at_rest=True` (Barbican stores ciphertext at rest)
    - `signs_values=False` (no signing)
    """
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


def _validate_path(value: str, label: str) -> None:
    if not value or not value.strip():
        raise SecretConfigurationException(
            f"barbican: {label} must be non-blank",
        )
    if ".." in value or "://" in value or value.startswith("/") or value.endswith("/"):
        raise SecretConfigurationException(
            f"barbican: {label} is invalid (no '..', '://', leading or trailing '/'): {value!r}",
        )


def _validate_endpoint(endpoint: str) -> None:
    if not endpoint or not endpoint.strip():
        raise SecretConfigurationException(
            "barbican: endpoint is required",
        )
    normalized = endpoint.strip().rstrip("/")
    if not (
        normalized.startswith("https://")
        or normalized.startswith("http://localhost")
        or normalized.startswith("http://127.0.0.1")
        or normalized.startswith("http://[::1]")
    ):
        raise SecretConfigurationException(
            f"barbican: endpoint must use https:// (or loopback http:// for dev): {endpoint!r}",
        )


def _validate_auth(auth_type: AuthType, token: str, token_file: str) -> None:
    if auth_type is AuthType.TOKEN_FILE:
        if not token_file or not token_file.strip():
            raise SecretConfigurationException(
                "barbican: TOKEN_FILE authentication requires auth_token_file",
            )
    elif auth_type is AuthType.TOKEN:
        if not token or not token.strip():
            raise SecretConfigurationException(
                "barbican: TOKEN authentication requires auth_token",
            )
    else:
        raise SecretConfigurationException(
            f"barbican: unknown auth_type: {auth_type!r}",
        )


def _validate_secret_mappings(secrets: Mapping[str, BarbicanSecretMapping]) -> None:
    for logical, mapping in secrets.items():
        if not logical or not logical.strip():
            raise SecretConfigurationException(
                f"barbican: secrets logical name must be non-blank: {logical!r}",
            )
        if mapping is None or not mapping.id or not mapping.id.strip():
            raise SecretConfigurationException(
                f"barbican: secrets[{logical!r}].id must be non-blank",
            )


@dataclass(frozen=True, slots=True)
class ResolvedBarbicanConfiguration:
    """Immutable result of resolving `BarbicanSecretProperties`.

    Attributes:
        provider_id: Stable identifier used in
            `SecretProviderDescriptor.name`. Defaults to
            ``"barbican"``; callers may override.
        properties: The (already pydantic-validated) properties.
        configuration_hash: SHA-256 hex digest over canonical
            fields.
        capability: Static capability of the Barbican backend.
    """

    provider_id: str
    properties: "object"  # forward-ref to BarbicanSecretProperties
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_barbican_capability)


class BarbicanConfigurationResolver:
    """Resolve `BarbicanSecretProperties` to a `ResolvedBarbicanConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "object",
        *,
        provider_id: str = "barbican",
    ) -> ResolvedBarbicanConfiguration:
        self._validate(properties)
        return ResolvedBarbicanConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _validate(properties: "object") -> None:
        _validate_endpoint(properties.endpoint)
        if properties.project_id is not None and properties.project_id.strip():
            if ".." in properties.project_id or "://" in properties.project_id:
                raise SecretConfigurationException(
                    f"barbican: project_id is invalid: {properties.project_id!r}",
                )
        _validate_auth(
            properties.auth_type,
            properties.auth_token,
            properties.auth_token_file or "",
        )
        _validate_secret_mappings(properties.secrets)

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "object",
    ) -> str:
        secrets_canonical = "\n".join(
            f"{k}={v.id}" for k, v in sorted(properties.secrets.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.endpoint}\n"
            f"{properties.project_id or ''}\n"
            f"{properties.auth_type.value}\n"
            f"{secrets_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedBarbicanConfiguration",
    "BarbicanConfigurationResolver",
]
