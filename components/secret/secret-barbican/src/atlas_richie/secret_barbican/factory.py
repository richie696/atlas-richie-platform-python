"""Barbican backend factory — `SecretProviderFactory` 入口。

中文
----
对位 Java `cn.richie696.component.secret.provider.barbican.BarbicanSecretBootstrapProviderFactory`
(单行 200+ 字符,Python 端拆成两函数)。

`BarbicanClientFactory`:构造 `httpx.Client`(对位 Java
`RemoteHttpClientFactory.create(...)`)。`httpx.Client` 内部用
`httpcore` 同步 HTTP,自带 timeout + retry;Python 端不实现
Java `HttpResponseRetryExecutor` 那种手工 retry — `httpx`
默认会重试一次(simple 模式),更复杂的 backoff 留给上层
resilience 子模块。

`BarbicanSecretProviderFactory`(`SecretProviderFactory`
Protocol 实现):
- `name` = `f"barbican-{project_id-or-host}"`
- `backend` = `SecretBackend.BARBICAN`
- `capability` = 静态声明(`can_read=True / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=True`,对位 Java 3-SPI scope)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 构造 `BarbicanClientFactory`
  2. 拿 `ResolvedBarbicanConfiguration`
  3. 构造 `BarbicanSecretClient`

English
--------
`SecretProviderFactory` for the Barbican backend. Mirrors
Java `BarbicanSecretBootstrapProviderFactory`. Builds a
`httpx.Client` (vs Java's JDK `HttpClient`); no manual
retry executor — `httpx` handles simple transient retries
internally. 3-SPI composite scope matches Java.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import httpx

from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_barbican.client import BarbicanSecretClient
from atlas_richie.secret_barbican.configuration import (
    BarbicanConfigurationResolver,
    ResolvedBarbicanConfiguration,
)
from atlas_richie.secret_barbican.properties import BarbicanSecretProperties

_logger = logging.getLogger("atlas_richie.secret_barbican.factory")


def _barbican_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=True,
    )


@runtime_checkable
class _HttpClientFactory(Protocol):
    """Test seam: tests may inject a pre-built `httpx.Client`
    (typically wrapping `httpx.MockTransport`) to skip real
    HTTP.
    """

    def __call__(self) -> httpx.Client: ...


def _default_http_factory(properties: BarbicanSecretProperties) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=properties.connect_timeout_seconds,
            read=properties.read_timeout_seconds,
            write=properties.read_timeout_seconds,
            pool=properties.connect_timeout_seconds,
        ),
    )


class BarbicanClientFactory:
    """Build an `httpx.Client` from `BarbicanSecretProperties`."""

    __slots__ = ()

    def create_http_client(self, properties: BarbicanSecretProperties) -> httpx.Client:
        return _default_http_factory(properties)


class BarbicanSecretProviderFactory:
    """`SecretProviderFactory` for the Barbican backend."""

    __slots__ = (
        "_client_factory",
        "_configuration_resolver",
        "_descriptor_backend",
        "_http_factory",
        "_name_override",
        "_properties",
        "_version",
    )

    def __init__(
        self,
        properties: BarbicanSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        http_factory: _HttpClientFactory | None = None,
        configuration_resolver: BarbicanConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.BARBICAN,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._http_factory = http_factory or (lambda: _default_http_factory(properties))
        self._configuration_resolver = (
            configuration_resolver or BarbicanConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> BarbicanSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        suffix = self._properties.project_id or self._properties.endpoint
        return f"barbican-{suffix}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _barbican_capability()

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
            timeout_seconds=self._properties.read_timeout_seconds,
            retries=self._properties.max_attempts,
            namespace=self._properties.endpoint,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        http_client = self._http_factory()
        resolved: ResolvedBarbicanConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return BarbicanSecretClient(
            resolved=resolved,
            http_client=http_client,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "BarbicanClientFactory",
    "BarbicanSecretProviderFactory",
]
