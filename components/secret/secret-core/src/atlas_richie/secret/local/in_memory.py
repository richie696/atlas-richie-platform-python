"""InMemory secret provider — 进程内字典存储,用于测试和 LocalSecret。

中文
----
对位 Java `cn.richie696.component.secret.provider.common` 的 in-memory 实现
(也对应 cache 端 `LocalCache` 的角色)。

`InMemorySecretProvider` 是 framework 自带的 backend,场景:

1. 单元测试 — 无需 Redis / Vault 等外部服务,直接构造注入 secret。
2. `LocalSecret` 应用场景 — 单进程内 secret 生命周期跟随应用,无
   远程依赖。
3. bootstrap 阶段 — 在外部 provider 还没初始化时,作为 fallback
   持有 bootstrap 阶段自身注入的 secret。

设计:

- **字典存储**:`dict[SecretReference, SecretValue]`,以 reference 为
  key(因为 `SecretReference` 是 frozen + hashable)。
- **不可变 view**:外部拿不到内部 dict;只能通过 `get` / `put` /
  `delete` 操作。
- **多版本支持**:每个 reference 维护一个 `dict[SecretVersion.number,
  SecretValue]`,`LATEST` 返回 `max(number)`。

线程安全:整 provider 用一个 `threading.Lock` 保护。InMemory 主要给
单线程 / 测试用,生产路径建议用 Redis / Vault。

English
--------
In-memory secret provider. Mirrors the in-memory backend of the Java
secret provider common sub-package. Suitable for unit tests, single-
process apps, and as a bootstrap fallback. Thread-safe via a single
`threading.Lock`.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone

from atlas_richie.secret.errors import SecretConfigurationException, SecretException, SecretIntegrityException
from atlas_richie.secret.metadata import SecretBackend, SecretCapability, SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.factory import SecretProviderFactory
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelectorKind,
)
from atlas_richie.secret.snapshot import SecretSnapshotChangedEvent, SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret.writer import SecretDeletable, SecretWriter


def _default_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=True,
        can_rotate=True,
        can_list=True,
        encrypts_at_rest=False,
        signs_values=False,
        cacheable=True,
    )


def _resolve_version(
    versions: dict[str, SecretValue],
    selector,
) -> SecretValue:
    if not versions:
        raise SecretIntegrityException("no versions stored")
    if selector.kind is SecretVersionSelectorKind.LATEST:
        latest_key = max(versions.keys())
        return versions[latest_key]
    if selector.kind is SecretVersionSelectorKind.STATIC:
        if selector.static_version is None:
            raise SecretConfigurationException(
                "STATIC selector requires SecretVersionSelector.static_version",
            )
        try:
            return versions[selector.static_version.number]
        except KeyError as error:
            raise SecretIntegrityException(
                f"version {selector.static_version.number!r} not found",
            ) from error
    if selector.kind is SecretVersionSelectorKind.PINNED_AT_TIME:
        candidates = [
            (value.metadata.version.created_at, value)
            for value in versions.values()
            if value.metadata.version.created_at is not None
            and value.metadata.version.created_at <= selector.pinned_at
        ]
        if not candidates:
            raise SecretIntegrityException(
                f"no version exists at or before {selector.pinned_at.isoformat()}",
            )
        candidates.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=timezone.utc))
        return candidates[-1][1]
    raise SecretConfigurationException(
        f"unsupported selector kind: {selector.kind!r}",
    )


class InMemorySecretOperations:
    """`SecretOperations` + `SecretListable` implementation backed by
    an in-process dict.
    """

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, SecretValue]] = defaultdict(dict)
        self._lock = threading.Lock()

    def store(self, reference: SecretReference, value: SecretValue) -> None:
        with self._lock:
            self._versions[reference.path][value.metadata.version.number] = value

    def get(self, reference: SecretReference) -> SecretValue:
        with self._lock:
            versions = self._versions.get(reference.path)
            if not versions:
                raise SecretIntegrityException(
                    f"secret not found: {reference.provider}:{reference.path}",
                )
            return _resolve_version(dict(versions), reference.version_selector)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        with self._lock:
            versions = self._versions.get(reference.path, {})
            try:
                return versions[version.number]
            except KeyError as error:
                raise SecretIntegrityException(
                    f"version {version.number!r} not found",
                ) from error

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        with self._lock:
            versions = self._versions.get(reference.path)
            if not versions:
                raise SecretIntegrityException(
                    f"secret not found: {reference.provider}:{reference.path}",
                )
            latest = _resolve_version(dict(versions), reference.version_selector)
            return latest.metadata

    def exists(self, reference: SecretReference) -> bool:
        with self._lock:
            return bool(self._versions.get(reference.path))

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        with self._lock:
            paths = sorted(path for path in self._versions if not prefix or path.startswith(prefix))
        return [
            SecretReference(provider="in_memory", path=path)
            for path in paths
        ]


class InMemorySecretWriter:
    """Write + rotate + delete for the in-memory backend."""

    def __init__(
        self,
        operations: InMemorySecretOperations,
        on_rotate: "callable[[SecretReference, SecretValue, SecretValue], None] | None" = None,
    ) -> None:
        self._operations = operations
        self._on_rotate = on_rotate
        self._version_counter = 0
        self._lock = threading.Lock()

    def _next_version(self) -> SecretVersion:
        with self._lock:
            self._version_counter += 1
            number = f"v{self._version_counter}"
        return SecretVersion(
            number=number,
            created_at=datetime.now(tz=timezone.utc),
        )

    def put(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        version = self._next_version()
        metadata = SecretMetadata(
            reference=reference,
            version=version,
            backend=SecretBackend.IN_MEMORY,
            created_at=version.created_at or datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={},
        )
        value = SecretValue(plaintext=plaintext, metadata=metadata)
        self._operations.store(reference, value)
        return value

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        previous = None
        try:
            previous = self._operations.get(reference)
        except SecretException:
            previous = None
        new_value = self.put(reference, new_plaintext)
        if self._on_rotate is not None:
            self._on_rotate(reference, previous, new_value)
        return new_value


class InMemorySecretDeletable:
    def __init__(self, operations: InMemorySecretOperations) -> None:
        self._operations = operations

    def delete(self, reference: SecretReference) -> None:
        with self._operations._lock:  # noqa: SLF001 - same package, same lock
            self._operations._versions.pop(reference.path, None)  # noqa: SLF001


class InMemorySecretProviderFactory:
    """`SecretProviderFactory` for the in-memory backend."""

    def __init__(self, name: str = "in_memory", version: str = "0.2.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.IN_MEMORY

    @property
    def capability(self) -> SecretCapability:
        return _default_capability()

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

    def create(
        self,
        configuration: SecretProviderConfiguration,
    ) -> SecretProviderSession:
        operations = InMemorySecretOperations()
        snapshot_manager = SecretSnapshotManager()

        def _on_rotate(
            reference: SecretReference,
            previous: SecretValue,
            current: SecretValue,
        ) -> None:
            snapshot_manager.publish(
                SecretSnapshotChangedEvent(
                    reference=reference,
                    previous_metadata=previous.metadata,
                    current_metadata=current.metadata,
                ),
            )

        writer = InMemorySecretWriter(operations, on_rotate=_on_rotate)
        deletable = InMemorySecretDeletable(operations)
        return _InMemorySession(
            configuration=configuration,
            descriptor=self.descriptor(),
            operations=operations,
            writer=writer,
            deletable=deletable,
            snapshot_manager=snapshot_manager,
        )


class _InMemorySession:
    """Concrete `SecretProviderSession` for the in-memory backend."""

    __slots__ = (
        "_configuration",
        "_descriptor",
        "_operations",
        "_writer",
        "_deletable",
        "_snapshot_manager",
        "_closed",
    )

    def __init__(
        self,
        *,
        configuration: SecretProviderConfiguration,
        descriptor: SecretProviderDescriptor,
        operations: SecretOperations,
        writer: SecretWriter,
        deletable: SecretDeletable,
        snapshot_manager: SecretSnapshotManager,
    ) -> None:
        self._configuration = configuration
        self._descriptor = descriptor
        self._operations = operations
        self._writer = writer
        self._deletable = deletable
        self._snapshot_manager = snapshot_manager
        self._closed = False

    @property
    def descriptor(self) -> SecretProviderDescriptor:
        return self._descriptor

    @property
    def configuration(self) -> SecretProviderConfiguration:
        return self._configuration

    @property
    def operations(self) -> SecretOperations:
        return self._operations

    @property
    def writer(self) -> SecretWriter | None:
        return self._writer

    @property
    def deletable(self) -> SecretDeletable | None:
        return self._deletable

    @property
    def snapshot_manager(self) -> SecretSnapshotManager:
        return self._snapshot_manager

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True


__all__ = [
    "InMemorySecretProviderFactory",
    "InMemorySecretOperations",
    "InMemorySecretWriter",
    "InMemorySecretDeletable",
]


# Ensure runtime-checkable Protocol imports stay self-consistent
_ = (SecretListable, SecretProviderFactory, SecretProviderSession)
