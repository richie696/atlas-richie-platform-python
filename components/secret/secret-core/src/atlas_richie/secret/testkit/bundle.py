"""Testkit bundle — provider factory + configuration 的成对容器。

中文
----
对位 Java `atlas-richie-secret-testkit.McpSecretEnvironmentStub` 角色。
`ProviderBundle` 把 factory + configuration 打包,供 conformance
测试一次性传入 `GlobalSecret.install()`。

设计:

- 单文件 + dataclass 即可,避免目录过深。
- `ProviderBundle` 是 frozen dataclass,线程安全。
- `ProviderBundle` 在 `SecretRegistry` 注册时同时记录 factory,便于
  框架反向 uninstall。

English
--------
Testkit bundle — pair of (factory, configuration) for installing a
backend in tests. Mirrors the role of Java's
`McpSecretEnvironmentStub`.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.factory import SecretProviderFactory


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """Pair of (factory, configuration) for installing a backend."""

    factory: SecretProviderFactory
    configuration: SecretProviderConfiguration


__all__ = ["ProviderBundle"]
