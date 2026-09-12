"""PKCS#11 factory — `SecretProviderFactory` + 内部 `Pkcs11ClientFactory`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

import pkcs11
from pkcs11.exceptions import PKCS11Error

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_pkcs11.client import Pkcs11SecretClient
from atlas_richie.secret_pkcs11.configuration import Pkcs11ConfigurationResolver
from atlas_richie.secret_pkcs11.properties import Pkcs11SecretProperties

_logger = logging.getLogger("atlas_richie.secret_pkcs11.factory")


@runtime_checkable
class _Pkcs11ClientFactory(Protocol):
    def __call__(
        self,
        properties: Pkcs11SecretProperties,
    ) -> tuple[Any, Any]: ...  # (lib, token)


class Pkcs11ClientFactory:
    """Build (lib, token) from `Pkcs11SecretProperties`."""

    __slots__ = ()

    def load_token(
        self,
        properties: Pkcs11SecretProperties,
    ) -> tuple[Any, Any]:
        try:
            lib = pkcs11.lib(properties.module_path)
            token = lib.get_token(token_label=properties.token_label)
        except PKCS11Error as error:
            raise SecretConfigurationException(
                f"pkcs11: failed to load token "
                f"(module={properties.module_path!r}, "
                f"label={properties.token_label!r}): {error}",
            ) from error
        return lib, token


def _default_client_factory(
    properties: Pkcs11SecretProperties,
) -> tuple[Any, Any]:
    return Pkcs11ClientFactory().load_token(properties)


class Pkcs11SecretProviderFactory:
    """`SecretProviderFactory` for the PKCS#11 HSM backend."""

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
        properties: Pkcs11SecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _Pkcs11ClientFactory | None = None,
        configuration_resolver: Pkcs11ConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.PKCS11,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or Pkcs11ConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> Pkcs11SecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"pkcs11-{self._properties.token_label}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return SecretCapability(
            can_read=False,
            can_write=False,
            can_rotate=False,
            can_list=False,
            encrypts_at_rest=True,
            signs_values=True,
            cacheable=False,
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
            retries=0,
            namespace=self._properties.token_label,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        lib, token = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return Pkcs11SecretClient(
            resolved=resolved,
            lib=lib,
            token=token,
            close_action=None,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "Pkcs11ClientFactory",
    "Pkcs11SecretProviderFactory",
]
