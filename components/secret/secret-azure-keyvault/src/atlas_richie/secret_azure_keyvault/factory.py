"""Azure Key Vault factory — `SecretProviderFactory` + 内部 `AzureClientFactory`。

中文
----
对位 Java `cn.richie696.component.secret.provider.azure.AzureSecretBootstrapProviderFactory`
+ 公共 `AbstractRemoteProviderFactory`。

`AzureClientFactory`(`create_clients(properties)`):负责
- 构造 `SecretClient`(`azure-keyvault-secrets`)
- 构造 `KeyClient`(`azure-keyvault-keys`)
- `DefaultAzureCredential` 处理 env / managed identity / Azure CLI

`AzureSecretProviderFactory`(`SecretProviderFactory` Protocol):
- `name` = `f"azure-{vault_url_hash}"`(URL 包含随机字符串,直接用
  URL 太长;取 SHA-256 头 8 字符)
- `backend` = `SecretBackend.AZURE`
- `capability` = 4-SPI 窄范围(对位 Java,无 sign/verify/list)

English
--------
Combined factory for Azure Key Vault. boto3's
`DefaultAzureCredential` covers the auth chain; the factory
just constructs the two SDK clients and wires them into the
4-SPI composite.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.keyvault.keys import KeyClient
from azure.keyvault.secrets import SecretClient

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_azure_keyvault.client import AzureSecretClient
from atlas_richie.secret_azure_keyvault.configuration import AzureConfigurationResolver
from atlas_richie.secret_azure_keyvault.properties import AzureSecretProperties

_logger = logging.getLogger("atlas_richie.secret_azure_keyvault.factory")


@runtime_checkable
class _AzureClientFactory(Protocol):
    """Test seam: tests inject a pre-built (SecretClient, KeyClient)
    pair to skip the Azure SDK bootstrap path."""

    def __call__(
        self,
        properties: AzureSecretProperties,
    ) -> tuple[object, object]: ...


class AzureClientFactory:
    """Build (SecretClient, KeyClient) from `AzureSecretProperties`."""

    __slots__ = ()

    def create_clients(
        self,
        properties: AzureSecretProperties,
    ) -> tuple[object, object]:
        try:
            credential = DefaultAzureCredential()
            secret_client = SecretClient(
                vault_url=properties.vault_url,
                credential=credential,
            )
            key_client = KeyClient(
                vault_url=properties.vault_url,
                credential=credential,
            )
        except AzureError as error:
            raise SecretConfigurationException(
                f"azure: failed to construct SDK clients "
                f"(vault_url={properties.vault_url!r}): {error}",
            ) from error
        return secret_client, key_client


def _default_client_factory(
    properties: AzureSecretProperties,
) -> tuple[object, object]:
    return AzureClientFactory().create_clients(properties)


class AzureSecretProviderFactory:
    """`SecretProviderFactory` for Azure Key Vault."""

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
        properties: AzureSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _AzureClientFactory | None = None,
        configuration_resolver: AzureConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.AZURE,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or AzureConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> AzureSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        # Vault URLs are long; hash to a short stable id.
        return f"azure-{hashlib.sha256(self._properties.vault_url.encode()).hexdigest()[:8]}"

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
            namespace=self._properties.vault_url,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        secret_client, key_client = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return AzureSecretClient(
            resolved=resolved,
            secret_client=secret_client,
            key_client=key_client,
            close_action=None,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "AzureClientFactory",
    "AzureSecretProviderFactory",
]
