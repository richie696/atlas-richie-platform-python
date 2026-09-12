"""Secret provider 会话 — provider 的运行时视图。

中文
----
对位 Java `cn.richie696.component.secret.api.provider.SecretProviderSession`。

`SecretProviderSession` 持有:

- `descriptor` — provider 元数据
- `operations` — `SecretOperations` 实现(读路径)
- `writer` — `SecretWriter` 可选实现(写路径)
- `deletable` — `SecretDeletable` 可选实现(硬删除)
- `snapshot_manager` — 内部 listener 注册表(可选)
- `configuration` — 构造时的配置,框架会回传给 `close()` 用于清理

会话生命周期:

- `open(configuration) -> Session` — factory 构造并 connect。
- `close() -> None` — backend 客户端释放(redis close / vault
  token 撤销 / file handle 关闭)。`close` 必须幂等。
- `is_closed -> bool` — 诊断。

`SecretProviderSession` 是 **不可变字段 + 可变内部状态** 的混合:
外部只读,`close()` 后所有 read/write 都抛 `SecretException`("session
closed")。

English
--------
Secret provider session. Mirrors the Java `SecretProviderSession`.
The session holds the backend client, the read/write/delete Protocol
implementations, the snapshot manager, and the original configuration
(needed at close time for backend-specific cleanup).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.writer import SecretDeletable, SecretWriter


@runtime_checkable
class SecretProviderSession(Protocol):
    """Runtime view of an active secret provider."""

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        ...

    @property
    def configuration(self) -> SecretProviderConfiguration:
        ...

    @property
    def operations(self) -> SecretOperations:
        ...

    @property
    def writer(self) -> SecretWriter | None:
        """``None`` if the backend is read-only."""
        ...

    @property
    def deletable(self) -> SecretDeletable | None:
        """``None`` if the backend does not support hard-delete."""
        ...

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        """Per-session listener registry. May be the same object across
        multiple sessions if the application wants a single fan-out.
        """
        ...

    @property
    def is_closed(self) -> bool:
        ...

    def close(self) -> None:
        """Release backend resources. Idempotent.

        After `close()`, any call into `operations` / `writer` /
        `deletable` MUST raise `SecretException` ("session closed").
        """
        ...


def ensure_open(session: SecretProviderSession) -> None:
    """Raise if the session has been closed. Used by provider
    implementations as a guard.
    """
    if session.is_closed:
        raise SecretException(
            f"provider session {session.descriptor.name!r} is closed",
        )


def list_capability(session: SecretProviderSession) -> bool:
    """Return whether `session.operations` supports listing."""
    return isinstance(session.operations, SecretListable)


__all__ = [
    "SecretProviderSession",
    "ensure_open",
    "list_capability",
]
