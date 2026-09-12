"""Secret 读操作契约。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretOperations`。

`SecretOperations` 是 backend 必须实现的最小读接口。Provider 在
`SecretProviderFactory.create()` 之后被框架调用,持有 backend 客户端
(redis client / hvac client / 文件句柄 / env 字典等)。

方法语义:

- `get(reference) -> SecretValue`:根据 reference 的 version_selector
  解析出实际版本,然后拉取。`LATEST` 默认。失败抛 `SecretException`。
- `get_version(reference, version)`:直接拉取指定版本,跳过 selector。
- `get_metadata(reference) -> SecretMetadata`:只读元数据,不解密。
  后端必须实现;不可用时抛 `SecretConfigurationException`。
- `exists(reference) -> bool`:判断 secret 是否存在。比 `get` 更轻,
  用于 resolver 启动期检测。
- `list(prefix) -> list[SecretReference]`:列已知 references。可选
  (取决于 `SecretCapability.can_list`);不支持时抛
  `SecretConfigurationException("list not supported")`。

`SecretOperations` 是 **read-only**;写入走 `SecretWriter` Protocol
(单写 / 旋转)。Provider 可以同时实现两个,也可以只读。

English
--------
Secret read operations contract. Mirrors the Java
`cn.richie696.component.secret.api.SecretOperations`. The Protocol
is the minimum surface a backend must implement for read-side flows;
write flows use `SecretWriter`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretConfigurationException, SecretException
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.value import SecretValue


@runtime_checkable
class SecretOperations(Protocol):
    """Read-side contract that every secret backend must implement."""

    def get(self, reference: SecretReference) -> SecretValue:
        """Resolve `reference.version_selector` and return the
        matching `SecretValue`. Implementations MUST decrypt /
        unwrap / verify any backend-side envelope before returning.
        """
        ...

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        """Read a specific version, bypassing the version selector."""
        ...

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        """Read metadata without fetching the plaintext value.

        Backends that cannot serve metadata-only reads (e.g. plain
        in-memory providers that do not track timestamps) should
        raise `SecretConfigurationException`.
        """
        ...

    def exists(self, reference: SecretReference) -> bool:
        """Return ``True`` if the secret currently has any version
        that can be resolved by `reference.version_selector`.
        """
        ...


@runtime_checkable
class SecretListable(Protocol):
    """Optional capability for backends that can enumerate references."""

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        """Return all known references, optionally filtered by `prefix`.

        Implementations must sort the result by `reference.path` for
        deterministic output (used by `testkit` and bootstrap catalog
        validation). Backends that do not support listing should
        raise `SecretConfigurationException("list not supported")`.
        """
        ...


# Stable, non-Protocol exports re-exposed for `from operations import X`
# convenience.
_ = (SecretException,)


__all__ = [
    "SecretOperations",
    "SecretListable",
    "SecretConfigurationException",
]
