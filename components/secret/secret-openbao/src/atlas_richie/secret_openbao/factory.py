"""OpenBao factory — thin wrapper over `VaultSecretProviderFactory`。

中文
----
对位 Java `cn.richie696.component.secret.provider.openbao.OpenBaoSecretBootstrapProviderFactory`。

设计:**thin wrapper**。OpenBao API 100% 兼容 Vault(KV v2 + Transit),
所以 OpenBao factory 唯一需要改的就是 metadata:
- `name` 前缀从 `vault-` 改成 `openbao-`
- `descriptor.backend` 从 `SecretBackend.VAULT` 改成 `SecretBackend.OPENBAO`
- `version` 字符串后缀加 `-openbao` 标识

其它(hvac 客户端构造 / auth strategy / 重试 / request-id / 5-SPI
composite / 路径安全 / SHA-256 configuration_hash)**全部**继承自
`VaultSecretProviderFactory` + `VaultSecretClient`,代码零重复。

为什么不开新实现:OpenBao 跟 Vault 走同一份 hvac SDK 调用、同
KV v2 / Transit API、同 auth 方法(Tokens / Kubernetes / AppRole
都是 OpenBao 1:1 兼容的),没有"独立实现"价值。等 OpenBao 偏离
时,在 `OpenBaoSecretProviderFactory.create()` 里 override 对应
行为即可。

English
--------
Thin wrapper over `VaultSecretProviderFactory`. Re-uses the
hvac client, auth strategies, retry, request-id, and 5-SPI
composite unchanged; only the metadata (name prefix /
descriptor.backend / version) is branded OpenBao.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import hvac

from atlas_richie.secret.metadata import SecretBackend, SecretCapability
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret_vault import (
    VaultClientFactory,
    VaultConfigurationResolver,
    VaultSecretProviderFactory,
)
from atlas_richie.secret_vault.client import VaultSecretClient

from atlas_richie.secret_openbao.properties import OpenBaoSecretProperties

if TYPE_CHECKING:
    from atlas_richie.secret.provider.session import SecretProviderSession


class OpenBaoSecretProviderFactory(VaultSecretProviderFactory):
    """`SecretProviderFactory` for OpenBao.

    Inherits all the SDK construction, auth strategy, retry,
    request-id, and 5-SPI composite behavior from
    `VaultSecretProviderFactory`. The only overrides are
    branding-related:

    - `name` default → `f"openbao-{namespace}"` (instead of
      `f"vault-{namespace}"`).
    - `descriptor.backend` → `SecretBackend.OPENBAO` (instead of
      `SecretBackend.VAULT`).
    - `version` → `f"{version}-openbao"` (default
      `"0.2.0-openbao"`).
    """

    __slots__ = ()

    def __init__(
        self,
        properties: OpenBaoSecretProperties,
        *,
        name: str | None = None,
        version: str = "0.2.0",
        client_factory: Callable[[OpenBaoSecretProperties], hvac.Client] | None = None,
        configuration_resolver: VaultConfigurationResolver | None = None,
    ) -> None:
        # Pass `descriptor_backend=OPENBAO` to the base class so
        # the produced `VaultSecretClient.descriptor.backend` is
        # branded OpenBao, while all the SDK construction logic
        # remains identical to the Vault path.
        super().__init__(
            properties=properties,
            name=name,
            version=version,
            client_factory=client_factory,  # type: ignore[arg-type]
            configuration_resolver=configuration_resolver,
            descriptor_backend=SecretBackend.OPENBAO,
        )

    @property
    def name(self) -> str:
        if self._name_override is not None:
            return self._name_override
        return f"openbao-{self._properties.namespace}"

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.OPENBAO

    @property
    def version(self) -> str:
        # The base class returns `self._version`; we re-suffix
        # it here so `descriptor.version = "0.2.0-openbao"` is
        # always branded, regardless of which version string
        # the caller passed (e.g. for an OpenBao-1.0 vs 2.0
        # split in the future).
        return f"{self._version}-openbao"

    def descriptor(self) -> SecretProviderDescriptor:
        return SecretProviderDescriptor(
            name=self.name,
            backend=self.backend,
            capability=SecretCapability(
                can_read=True,
                can_write=True,
                can_rotate=True,
                can_list=False,
                encrypts_at_rest=True,
                signs_values=False,
                cacheable=True,
            ),
            version=self.version,
        )


# Re-export so consumers don't need to import `VaultSecretClient`
# directly from the underlying wheel. The VaultSecretClient
# instance is the same — only the `descriptor.backend` differs.
__all__ = [
    "OpenBaoSecretProviderFactory",
    "VaultSecretClient",
    "VaultClientFactory",
]


# Local-var sentinel: a type hint to readers that
# `VaultSecretClient` is intentionally surfaced here as the
# concrete return type of `create()`.
_ = (Callable,)
