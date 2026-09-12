"""Secret 写操作契约(写入 / 更新 / 旋转 / 删除)。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretWriter` /
`cn.richie696.component.secret.api.SecretVersionSelector`。

`SecretWriter` 是 backend 的可选写接口(由 `SecretCapability.can_write`
决定是否暴露给 facade)。读-only backend 不实现 `SecretWriter`,
framework 在 facade 层用 `hasattr(provider, "write")` 探测。

方法语义:

- `put(reference, plaintext) -> SecretValue`:创建或覆盖(取决于
  backend 语义:Redis 用 `SET`,Vault 用 `kv put`)。返回新写入的
  `SecretValue`(含新版本号 + metadata)。
- `rotate(reference, new_plaintext) -> SecretValue`:原子旋转,生成
  新版本号(单调递增)。失败抛 `SecretException`。
- `delete(reference) -> None`:硬删除所有版本(谨慎使用)。`SecretWriter`
  实现必须实现 `put` + `rotate`;`delete` 可选(由
  `SecretCapability.can_write` 之外的 `can_delete` 决定)。

旋转语义保证:

1. 写新版本前,旧版本继续可读(直到 cache TTL 过期或后台 GC 清理)。
2. `SecretSnapshotManager.publish(...)` 在 `rotate` 成功后被自动
   触发(由 `DefaultSecretResolver` 在写后调用);若 backend 自身已
   触发,框架不重复触发。

English
--------
Secret write operations contract. Mirrors the Java
`cn.richie696.component.secret.api.SecretWriter`. The Protocol is
optional; read-only backends do not implement it. `SecretCapability`
drives the facade's runtime decision to expose write APIs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.reference import SecretReference
from atlas_richie.secret.value import SecretValue


@runtime_checkable
class SecretWriter(Protocol):
    """Write-side contract. Optional capability; see `SecretCapability`."""

    def put(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        """Create a new secret or overwrite the latest version.

        Atomicity: implementations MUST be atomic at the backend
        level (e.g. Redis `SET`, Vault `kv put` with `cas=0`). The
        returned `SecretValue` includes the new version number and
        metadata.
        """
        ...

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        """Atomic rotation producing a new monotonic version.

        The previous version MUST remain readable until the backend
        GCs it (callers that need stricter semantics can use
        `SecretSnapshotManager` to observe rotations).
        """
        ...


@runtime_checkable
class SecretDeletable(Protocol):
    """Optional capability: hard-delete a secret and all its versions."""

    def delete(self, reference: SecretReference) -> None:
        """Hard-delete the secret at `reference`. After this call,
        `SecretOperations.exists` MUST return ``False`` and reads
        MUST raise `SecretIntegrityException` (not-found is treated
        as an integrity error to surface stale callers).
        """
        ...


__all__ = [
    "SecretWriter",
    "SecretDeletable",
]
