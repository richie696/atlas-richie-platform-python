"""GCP Secret Manager + KMS factory."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import google.auth
import google.auth.exceptions
from google.cloud.kms import KeyManagementServiceClient
from google.cloud.secretmanager_v1 import SecretManagerServiceClient

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_gcp_kms.client import GcpSecretClient
from atlas_richie.secret_gcp_kms.configuration import GcpConfigurationResolver
from atlas_richie.secret_gcp_kms.properties import GcpSecretProperties

_logger = logging.getLogger("atlas_richie.secret_gcp_kms.factory")


@runtime_checkable
class _GcpClientFactory(Protocol):
    def __call__(
        self,
        properties: GcpSecretProperties,
    ) -> tuple[object, object]: ...


class GcpClientFactory:
    """Build (SecretManagerServiceClient, KeyManagementServiceClient)
    from `GcpSecretProperties`. Uses Application Default
    Credentials (ADC) for auth.
    """

    __slots__ = ()

    def create_clients(
        self,
        properties: GcpSecretProperties,
    ) -> tuple[object, object]:
        try:
            google.auth.default()
            sm = SecretManagerServiceClient()
            kms = KeyManagementServiceClient()
        except google.auth.exceptions.DefaultCredentialsError as error:
            raise SecretConfigurationException(
                f"gcp: failed to construct SDK clients "
                f"(project_id={properties.project_id!r}): {error}",
            ) from error
        return sm, kms


def _default_client_factory(
    properties: GcpSecretProperties,
) -> tuple[object, object]:
    return GcpClientFactory().create_clients(properties)


class GcpSecretProviderFactory:
    """`SecretProviderFactory` for the GCP backend."""

    __slots__ = (
        "_client_factory",
        "_configuration_resolver",
        "_descriptor_backend",
        "_name_override",
        "_properties",
        "_version",
    )

    def __init__(
        self,
        properties: GcpSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _GcpClientFactory | None = None,
        configuration_resolver: GcpConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.GCP,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or GcpConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> GcpSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"gcp-{self._properties.project_id}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return SecretCapability(
            can_read=True,
            can_write=False,
            can_rotate=True,
            can_list=False,
            encrypts_at_rest=True,
            signs_values=False,
            cacheable=True,
        )

    @property
    def version(self) -> str:
        return self._version

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=self.capability,
            version=self.version,
        )

    def default_configuration(self) -> SecretProviderConfiguration:
        return SecretProviderConfiguration(
            name=self.name,
            parameters={},
            timeout_seconds=self._properties.timeout_seconds,
            retries=3,
            namespace=self._properties.project_id,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        sm_client, kms_client = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return GcpSecretClient(
            resolved=resolved,
            sm_client=sm_client,
            kms_client=kms_client,
            close_action=None,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "GcpClientFactory",
    "GcpSecretProviderFactory",
]
