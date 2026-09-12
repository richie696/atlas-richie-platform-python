"""Vault backend factory — `SecretProviderFactory` + 内部 `VaultClientFactory`。

中文
----
对位 Java `cn.richie696.component.secret.provider.vault.VaultClientFactory` +
`VaultSecretBootstrapProviderFactory`。Java 端一个类做 SDK 构造,
另一个做 bootstrap;Python 端把两者合一放在 `factory.py`,framework
端只看到 `SecretProviderFactory` Protocol。

`VaultClientFactory`(`create_hvac_client(properties)`):负责
- 从 `VaultSecretProperties.to_hvac_client_kwargs()` 拿 kwargs
- 构造 `hvac.Client`
- 应用 `auth_strategy_for(properties)`(Token / K8s / AppRole)

`VaultSecretProviderFactory`(`SecretProviderFactory` Protocol 实现):
- `name` = `f"vault-{namespace}"`(对位 Redis 仓的命名约定)
- `backend` = `SecretBackend.VAULT`
- `capability` = 静态声明(只读 + 加密存储 + cacheable + 无 list)
- `version` = `"0.2.0"`
- `create(configuration) -> SecretProviderSession`:
  1. 用 `VaultClientFactory` 拿 authenticated hvac.Client
  2. 用 `VaultConfigurationResolver` 拿 `ResolvedVaultConfiguration`
  3. 构造 `VaultSecretClient`
  4. 用 `hvac.Client` 上下文管理器式 `close` 包装 close_action

错误转译:
- `hvac.Client(url=...)` 失败 → `SecretConfigurationException`
- `auth_strategy.apply(...)` 失败 → 由 auth.py 转译为 `SecretException`
- 其它 → 透传,不在 factory 层加包装

English
--------
Combined factory for the Vault backend. Mirrors Java
`VaultClientFactory` + `VaultSecretBootstrapProviderFactory`. The
Python side keeps both responsibilities in one module because they
share the same lifecycle: `VaultClientFactory.create_hvac_client`
materializes and authenticates the `hvac.Client`;
`VaultSecretProviderFactory.create(...)` wraps it in a
`VaultSecretClient` and returns a `SecretProviderSession`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import hvac

from atlas_richie.secret.errors import SecretConfigurationException, SecretException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret_vault.auth import auth_strategy_for
from atlas_richie.secret_vault.client import VaultSecretClient
from atlas_richie.secret_vault.configuration import VaultConfigurationResolver
from atlas_richie.secret_vault.properties import VaultSecretProperties

_logger = logging.getLogger("atlas_richie.secret_vault.factory")


@runtime_checkable
class _HvacClientFactory(Protocol):
    """Test seam: allows tests to inject a fake hvac client.

    Production code uses `VaultClientFactory.create_hvac_client`;
    tests may pass a closure that returns a pre-authenticated
    `hvac.Client` to skip the network round-trip.
    """

    def __call__(self, properties: VaultSecretProperties) -> hvac.Client: ...


class VaultClientFactory:
    """Materialize and authenticate an `hvac.Client` from
    `VaultSecretProperties`.

    Mirrors Java `VaultClientFactory.create(...)` minus the
    Spring-RestTemplate setup (hvac already manages HTTP via
    `requests.Session`).
    """

    __slots__ = ()

    def create_hvac_client(self, properties: VaultSecretProperties) -> hvac.Client:
        kwargs = properties.to_hvac_client_kwargs()
        try:
            client = hvac.Client(**kwargs)
        except Exception as error:  # noqa: BLE001
            raise SecretConfigurationException(
                f"vault: failed to construct hvac.Client "
                f"(url={properties.url!r}): {error}",
            ) from error
        # Apply the configured auth strategy. For Token auth, this
        # also runs a `lookup_self` to confirm the token is alive
        # at construction time; for K8s / AppRole it triggers the
        # actual login.
        try:
            auth_strategy_for(properties).apply(client)
        except SecretException:
            raise
        except Exception as error:  # noqa: BLE001
            raise SecretException(
                f"vault: auth.apply failed: {error}",
            ) from error
        return client


def _default_client_factory(properties: VaultSecretProperties) -> hvac.Client:
    """Module-level default factory function.

    Lives outside the class so it can be referenced by the
    `VaultSecretProviderFactory` default without forcing the
    class to be instantiated first.
    """
    return VaultClientFactory().create_hvac_client(properties)


class VaultSecretProviderFactory:
    """`SecretProviderFactory` for the Vault backend.

    Construction takes the env-validated `VaultSecretProperties`;
    `create(configuration)` materializes a hvac.Client via the
    configured (or default) client factory, runs the
    `VaultConfigurationResolver` to compute the immutable
    `ResolvedVaultConfiguration`, then constructs a
    `VaultSecretClient` that satisfies `SecretProviderSession`.
    """

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
        properties: VaultSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: _HvacClientFactory | None = None,
        configuration_resolver: VaultConfigurationResolver | None = None,
        descriptor_backend: SecretBackend = SecretBackend.VAULT,
    ) -> None:
        self._properties = properties
        self._name_override = name
        self._version = version
        self._client_factory = client_factory or _default_client_factory
        self._configuration_resolver = (
            configuration_resolver or VaultConfigurationResolver()
        )
        # Lets the OpenBao wheel (R-233.4) re-use this factory with
        # a different `SecretBackend` value on the produced
        # `VaultSecretClient.descriptor`. Defaults to VAULT so
        # existing callers see no change.
        self._descriptor_backend = descriptor_backend

    @property
    def properties(self) -> VaultSecretProperties:
        return self._properties

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"vault-{self._properties.namespace}"

    @property
    def backend(self) -> SecretBackend:
        return self._descriptor_backend

    @property
    def capability(self) -> SecretCapability:
        return SecretCapability(
            can_read=True,
            can_write=True,
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
        """Build a `SecretProviderConfiguration` from the embedded
        `VaultSecretProperties`.

        Callers that already have a `SecretProviderConfiguration`
        (e.g. from the framework registry) may pass it to
        `create(configuration)` instead.
        """
        return SecretProviderConfiguration(
            name=self.name,
            parameters={},
            timeout_seconds=self._properties.timeout_seconds,
            retries=self._properties.max_retries,
            namespace=self._properties.namespace,
        )

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        hvac_client = self._client_factory(self._properties)
        resolved = self._configuration_resolver.resolve(
            self._properties,
            provider_id=configuration.name or self.name,
        )
        try:
            client = VaultSecretClient(
                resolved=resolved,
                hvac_client=hvac_client,
                close_action=_make_close_action(hvac_client),
                descriptor_backend=self._descriptor_backend,
            )
        except Exception as error:
            # Tear down the partially-constructed hvac.Client so
            # the test / framework doesn't leak the underlying
            # `requests.Session`.
            try:
                hvac_client.logout()
            except Exception:  # noqa: BLE001
                pass
            raise SecretException(
                f"vault: failed to construct VaultSecretClient: {error}",
            ) from error
        return client


def _make_close_action(hvac_client: hvac.Client) -> Callable[[], None]:
    """Build a `close_action` that revokes the hvac session token.

    `hvac.Client` does not own a persistent connection in the
    `redis-py` sense; the only resource to release is the
    currently-active Vault token. `client.logout()` revokes it on
    the server side. Wrapped in try/except so a Vault 4xx
    response (e.g. token already expired) does not break the
    framework's own cleanup chain.
    """
    def _close() -> None:
        try:
            hvac_client.logout()
        except Exception:  # noqa: BLE001
            _logger.debug(
                "vault: hvac.Client.logout() raised; treating as no-op",
                exc_info=True,
            )
    return _close


__all__ = [
    "VaultClientFactory",
    "VaultSecretProviderFactory",
]
