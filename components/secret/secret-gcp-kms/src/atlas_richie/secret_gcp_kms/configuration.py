"""GCP configuration resolver — path safety + SHA-256 hash."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability

if TYPE_CHECKING:
    from atlas_richie.secret_gcp_kms.properties import GcpSecretProperties


def _gcp_capability() -> SecretCapability:
    """Static capability for the GCP Secret Manager + KMS backend.

    Mirrors Java `providerCapabilities` on
    `GcpSecretBootstrapProviderFactory`:
    - `SECRET_READ` / `SECRET_VERSIONING` (Secret Manager API)
    - `KEY_WRAP` / `KEY_UNWRAP` (KMS encrypt / decrypt)

    NOT exposed (Java does not declare):
    - `SECRET_LIST`
    - `SIGN` / `VERIFY`
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


@dataclass(frozen=True, slots=True)
class ResolvedGcpConfiguration:
    """Immutable result of resolving `GcpSecretProperties`."""

    provider_id: str
    properties: "GcpSecretProperties"
    configuration_hash: str
    capability: SecretCapability = field(default_factory=_gcp_capability)


class GcpConfigurationResolver:
    """Resolve `GcpSecretProperties` to a `ResolvedGcpConfiguration`."""

    __slots__ = ()

    def resolve(
        self,
        properties: "GcpSecretProperties",
        *,
        provider_id: str = "gcp-main",
    ) -> ResolvedGcpConfiguration:
        if not properties.project_id:
            raise SecretConfigurationException(
                "gcp: project_id is required",
            )
        return ResolvedGcpConfiguration(
            provider_id=provider_id,
            properties=properties,
            configuration_hash=self._configuration_hash(provider_id, properties),
        )

    @staticmethod
    def _configuration_hash(
        provider_id: str,
        properties: "GcpSecretProperties",
    ) -> str:
        bindings = properties.kms_key_bindings or {}
        bindings_canonical = "\n".join(
            f"{k}={v}" for k, v in sorted(bindings.items())
        )
        canonical = (
            f"{provider_id}\n"
            f"{properties.project_id}\n"
            f"{properties.kms_location}\n"
            f"{properties.kms_key_ring}\n"
            f"{bindings_canonical}\n"
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "ResolvedGcpConfiguration",
    "GcpConfigurationResolver",
]
