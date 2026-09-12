"""PKCS#11 configuration resolver — path safety + SHA-256 hash."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

if TYPE_CHECKING:
    from atlas_richie.secret_pkcs11.properties import Pkcs11SecretProperties


def _pkcs11_capability() -> SecretCapability:
    """Static capability for the PKCS#11 HSM backend.

    Mirrors Java `Pkcs11SecretClient` capabilities:
    - `KEY_WRAP` / `KEY_UNWRAP` (RSA wrap / unwrap)
    - `SIGN` / `VERIFY` (RSA / ECDSA sign / verify)

    NOT exposed (HSM has no storage):
    - `SECRET_READ` / `SECRET_VERSIONING` / `SECRET_LIST`
    - `SECRET_WRITE` / `SECRET_ROTATE`
    """
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,  # HSM never exposes plaintext keys
        signs_values=True,
        cacheable=False,  # HSM ops are stateful; cache sparingly
    )


@dataclass(frozen=True, slots=True)
class ResolvedPkcs11Configuration:
    """Immutable result of resolving `Pkcs11SecretProperties`."""

    provider_id: str
    properties: "Pkcs11SecretProperties"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_pkcs11_capability)


class Pkcs11ConfigurationResolver:
    """Resolve `Pkcs11SecretProperties` to `ResolvedPkcs11Configuration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "Pkcs11SecretProperties",
        *,
        provider_id: str = "pkcs11-main",
    ) -> ResolvedPkcs11Configuration:
        if not properties.module_path:
            raise SecretConfigurationException(
                "pkcs11: module_path is required",
            )
        if not properties.token_label:
            raise SecretConfigurationException(
                "pkcs11: token_label is required",
            )
        return ResolvedPkcs11Configuration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "Pkcs11SecretProperties",
    ) -> str:
        bindings = properties.key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.module_path}\n"
            f"{properties.token_label}\n"
            f"{properties.default_sign_mechanism.value}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedPkcs11Configuration",
    "Pkcs11ConfigurationResolver",
]
