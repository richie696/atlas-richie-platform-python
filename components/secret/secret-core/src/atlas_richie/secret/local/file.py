"""File secret provider — 从本地文件读 secret。

中文
----
对位 Java `cn.richie696.component.secret.provider.common` 的 file 适配。

`FileSecretProvider` 把 `SecretReference.path` 当作相对路径(基目录由
`SecretProviderConfiguration.parameters["base_dir"]` 指定),读文件
内容作 secret value。典型场景:

- Kubernetes `volumeMounts` 挂载 `Secret` 对象到 Pod 内 `/var/run/secrets/...`
- HashiCorp Vault Agent 在本地写 `~/.vault-token` 等短期凭证
- Dev / test fixture 文件

设计:

- **path 解析**:`base_dir + namespace + path`(可配置),用 `pathlib.Path`
  校验不越界(`..` / 绝对路径都拒绝,防目录穿越)。
- **原子读**:每次 `get` 都重新打开(不缓存),保证外部 rotate 立刻可见。
- **多版本**:`get_version(vN)` 通过 `<base>/<path>.vN` 解析;若文件
  不存在则抛 `SecretIntegrityException`。
- **写 / 旋转 / 删除**:支持,但走"先写临时文件 + rename"模式,确保
  rotate 期间 `get` 不会看到空文件。

English
--------
File secret provider. Mirrors the Java file backend. `base_dir` comes
from `SecretProviderConfiguration.parameters["base_dir"]`. Reads
always open fresh (no cache) so external rotations are visible
immediately. Writes use write-then-rename for atomicity.
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretCryptoException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretCapability, SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotChangedEvent, SecretSnapshotManager
from atlas_richie.secret.value import SecretValue
from atlas_richie.secret.writer import SecretDeletable, SecretWriter


def _file_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=True,
        can_rotate=True,
        can_list=True,
        encrypts_at_rest=False,
        signs_values=False,
        cacheable=False,  # file reads are always fresh
    )


def _resolve(base_dir: Path, namespace: str, path: str) -> Path:
    if path.startswith("/") or ".." in Path(path).parts:
        raise SecretConfigurationException(
            f"invalid secret path (must be relative, no ..): {path!r}",
        )
    return base_dir / namespace / path


class FileSecretOperations:
    """Read + list from the file system."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._lock = threading.Lock()

    def _read(self, full_path: Path, reference: SecretReference) -> SecretValue:
        try:
            content = full_path.read_bytes()
        except FileNotFoundError as error:
            raise SecretIntegrityException(
                f"secret file not found: {full_path}",
            ) from error
        except OSError as error:
            raise SecretCryptoException(
                f"failed to read secret file {full_path}: {error}",
            ) from error
        version = SecretVersion(number="current", created_at=None)
        stat = full_path.stat()
        created = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        metadata = SecretMetadata(
            reference=reference,
            version=version,
            backend=SecretBackend.FILE,
            created_at=created,
            expires_at=None,
            tags={"path": str(full_path)},
        )
        return SecretValue(plaintext=content, metadata=metadata)

    def get(self, reference: SecretReference) -> SecretValue:
        with self._lock:
            return self._read(_resolve(self._base_dir, "", reference.path), reference)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        with self._lock:
            versioned_path = f"{reference.path}.{version.number}"
            return self._read(_resolve(self._base_dir, "", versioned_path), reference)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        return self.get(reference).metadata

    def exists(self, reference: SecretReference) -> bool:
        with self._lock:
            return _resolve(self._base_dir, "", reference.path).is_file()

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        with self._lock:
            if not self._base_dir.exists():
                return []
            paths = sorted(
                str(p.relative_to(self._base_dir))
                for p in self._base_dir.rglob("*")
                if p.is_file()
            )
        if prefix is None:
            return [SecretReference(provider="file", path=p) for p in paths]
        return [
            SecretReference(provider="file", path=p)
            for p in paths
            if p.startswith(prefix)
        ]


class FileSecretWriter:
    """Write + rotate + delete for the file backend. Atomic via
    write-then-rename.
    """

    def __init__(self, base_dir: Path, snapshot_manager: SecretSnapshotManager) -> None:
        self._base_dir = base_dir
        self._snapshot_manager = snapshot_manager
        self._lock = threading.Lock()
        self._version_counter = 0

    def _next_version(self) -> SecretVersion:
        with self._lock:
            self._version_counter += 1
            number = f"v{self._version_counter}"
        return SecretVersion(number=number, created_at=datetime.now(tz=timezone.utc))

    def _atomic_write(self, full_path: Path, plaintext: bytes) -> None:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a sibling temp file then rename. Use NamedTemporaryFile
        # with delete=False to avoid leaving a half-written file on
        # failure.
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{full_path.name}.",
            dir=str(full_path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as fp:
                fp.write(plaintext)
            os.replace(tmp_name, full_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def put(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        full_path = _resolve(self._base_dir, "", reference.path)
        with self._lock:
            self._atomic_write(full_path, plaintext)
        version = self._next_version()
        metadata = SecretMetadata(
            reference=reference,
            version=version,
            backend=SecretBackend.FILE,
            created_at=version.created_at or datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={"path": str(full_path)},
        )
        return SecretValue(plaintext=plaintext, metadata=metadata)

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        new_value = self.put(reference, new_plaintext)
        self._snapshot_manager.publish(
            SecretSnapshotChangedEvent(
                reference=reference,
                previous_metadata=None,
                current_metadata=new_value.metadata,
            ),
        )
        return new_value


class FileSecretDeletable:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def delete(self, reference: SecretReference) -> None:
        full_path = _resolve(self._base_dir, "", reference.path)
        try:
            full_path.unlink()
        except FileNotFoundError as error:
            raise SecretIntegrityException(
                f"secret file not found: {full_path}",
            ) from error


class FileSecretProviderFactory:
    """`SecretProviderFactory` for the file backend."""

    def __init__(self, name: str = "file", version: str = "0.2.0") -> None:
        self._name = name
        self._version = version

    @property
    def name(self) -> str:
        return self._name

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.FILE

    @property
    def capability(self) -> SecretCapability:
        return _file_capability()

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
        raw = configuration.parameters.get("base_dir")
        if not raw:
            raise SecretConfigurationException(
                "file: SecretProviderConfiguration.parameters['base_dir'] is required",
            )
        base_dir = Path(raw).resolve()
        operations = FileSecretOperations(base_dir=base_dir)
        snapshot_manager = SecretSnapshotManager()
        writer = FileSecretWriter(base_dir=base_dir, snapshot_manager=snapshot_manager)
        deletable = FileSecretDeletable(base_dir=base_dir)
        return _FileSession(
            configuration=configuration,
            descriptor=self.descriptor(),
            operations=operations,
            writer=writer,
            deletable=deletable,
            snapshot_manager=snapshot_manager,
        )


class _FileSession:
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
    "FileSecretProviderFactory",
    "FileSecretOperations",
    "FileSecretWriter",
    "FileSecretDeletable",
]


_ = (SecretListable, SecretProviderSession, Mapping)
