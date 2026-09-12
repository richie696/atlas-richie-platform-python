"""KMIP backend factory — `SecretProviderFactory` 入口。

中文
----
对位 Java `cn.richie696.component.secret.provider.kmip.KmipSecretBootstrapProviderFactory`
(单行 200+ 字符,Python 端拆成两函数)。`AliyunClientFactory` →
`KmipClientFactory`(SSL context 构造 + `KmipSecretClient` 装配)。

`create_ssl_context(properties)`:对位 Java
`KmipSecretClient.sslSocketFactory`,从 `properties.trust_store`
/ `properties.key_store` 构造 `ssl.SSLContext`。`SSLContext`
必须在每次 factory 调用时构造(stale 缓存不适用,因为
trust store 可能在工厂生命周期中改变)。

`KmipSecretProviderFactory`(`SecretProviderFactory` Protocol
实现):
- `name` = `f"kmip-{host}"`(host 是 endpoint 的 hostname)
- `backend` = `SecretBackend.PKCS11`(对位 Java
  `KmipSecretClient.secretBackend().isEmpty()` + 复用
  HSM 的 `SecretBackend.PKCS11` 标签 — Java 端没有
  `KMIP = "kmip"` 枚举值,只是 metadata tag)
- `capability` = 静态声明(`can_read=False / can_write=False /
  can_rotate=False / can_list=False / encrypts_at_rest=True /
  signs_values=False / cacheable=False`,对位 Java 2-SPI scope)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 构造 `ssl.SSLContext`
  2. 用 `KmipConfigurationResolver` 拿 `ResolvedKmipConfiguration`
  3. 构造 `KmipSecretClient`

**secret-core 没有 `KMIP` 枚举值**:Java 端也没有对应
`SecretBackend.KMIP = "kmip"`,因为 KMIP 抽象的是 KMS
后端而不是 HSM。Python 端复用 `SecretBackend.PKCS11`
作为 placeholder 标签(framework metadata 只用于
observability / 路由)。

English
--------
`SecretProviderFactory` for the KMIP backend. Mirrors
Java `KmipSecretBootstrapProviderFactory`. The factory
constructs an `ssl.SSLContext` from the configured
trust / key stores and wires a `KmipSecretClient`.
"""

from __future__ import annotations

import ssl
from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretConfigurationException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_kmip.client import (
    KmipSecretClient,
    _parse_endpoint,
)
from atlas_richie.secret_kmip.configuration import (
    KmipConfigurationResolver,
    ResolvedKmipConfiguration,
)
from atlas_richie.secret_kmip.properties import KmipSecretProperties

_BACKEND = SecretBackend.PKCS11  # placeholder; KMIP has no SecretBackend enum


def _kmip_capability() -> SecretCapability:
    return SecretCapability(
        can_read=False,
        can_write=False,
        can_rotate=False,
        can_list=False,
        encrypts_at_rest=True,
        signs_values=False,
        cacheable=False,
    )


@runtime_checkable
class _SslContextFactory(Protocol):
    """Test seam: tests may inject a pre-built `ssl.SSLContext`
    to skip the trust store / key store path entirely.
    """

    def __call__(self, properties: KmipSecretProperties) -> ssl.SSLContext: ...


def _default_ssl_factory(properties: KmipSecretProperties) -> ssl.SSLContext:
    """Build the default `ssl.SSLContext` from properties.

    Mirrors Java's `KmipSecretClient.sslSocketFactory`:
    - `trust_store` is set → load_verify_locations
    - `key_store` is set → load_cert_chain (mutual TLS)
    - hostname verification: **off** (KMIP servers often
      use bare IPs / internal names; trust is governed by
      the trust store, not the hostname check)
    """
    if properties.trust_store:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cafile=properties.trust_store)
        ctx.verify_mode = ssl.CERT_REQUIRED
    else:
        ctx = ssl.create_default_context()
        ctx.verify_mode = ssl.CERT_NONE
    if properties.key_store:
        ctx.load_cert_chain(
            certfile=properties.key_store,
            password=properties.key_store_password,
        )
    ctx.check_hostname = False
    return ctx


class KmipClientFactory:
    """Build a `ssl.SSLContext` from `KmipSecretProperties`."""

    __slots__ = ()

    def create_ssl_context(self, properties: KmipSecretProperties) -> ssl.SSLContext:
        return _default_ssl_factory(properties)


class KmipSecretProviderFactory:
    """`SecretProviderFactory` for the KMIP backend."""

    __slots__ = (
        "_client_factory",
        "_configuration_resolver",
        "_descriptor_backend",
        "_name_override",
        "_properties",
        "_ssl_factory",
        "_version",
    )

    def __init__(
        self,
        properties: KmipSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        ssl_factory: _SslContextFactory | None = None,
        configuration_resolver: KmipConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = _BACKEND,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._ssl_factory = ssl_factory or _default_ssl_factory
        self._configuration_resolver = (
            configuration_resolver or KmipConfigurationResolver()
        )
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> KmipSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"kmip-{_parse_endpoint(self._properties.endpoint).host}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return _kmip_capability()

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
        ssl_context = self._ssl_factory(self._properties)
        resolved: ResolvedKmipConfiguration = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        return KmipSecretClient(
            resolved=resolved,
            ssl_context=ssl_context,
            descriptor_backend=self._descriptor_backend,
        )


__all__ = [
    "KmipClientFactory",
    "KmipSecretProviderFactory",
]
