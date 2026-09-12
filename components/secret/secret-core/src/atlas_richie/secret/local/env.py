"""Env secret provider — 从环境变量读 secret。

中文
----
对位 Java `cn.richie696.component.secret.provider.common` 的 env 适配。

`EnvSecretProvider` 从 `os.environ` 读 secret,典型场景:

- 容器化部署(Kubernetes Pod / Docker)直接 `envFrom: secretKeyRef` 注入
- 开发环境 `.env` 文件 / `export VAR=value`
- CI runner 临时环境变量

设计:

- **路径 → env 变量名**:`SecretReference.path` 直接当 env 变量名
  (大写 + 下划线),不转换。`EnvSecretProvider(upper=True)` 构造选项
  会把 path 转大写。
- **多版本**:环境变量天然单值,没有"v1 / v2"概念。`get_version` 抛
  `SecretConfigurationException("env: not versioned")`。
- **写 / 旋转 / 删除**:环境变量在大多数 OS 上是只读于子进程;framework
  在 `writer` 上抛 `SecretConfigurationException`,提醒调用方走
  bootstrap 阶段的 setter。

English
--------
Env secret provider. Mirrors the Java env-var backend. Reads secrets
from `os.environ`; optional `upper=True` constructor flag uppercases
the `SecretReference.path` before lookup. No versioning (env vars
are inherently single-valued).
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretBackend, SecretCapability, SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.provider.descriptor import SecretProviderDescriptor
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import (
    SecretReference,
    SecretVersion,
    SecretVersionSelectorKind,
)
from atlas_richie.secret.value import SecretValue


def _env_capability() -> SecretCapability:
    return SecretCapability(
        can_read=True,
        can_write=False,  # env vars are read-only at runtime
        can_rotate=False,
        can_list=True,
        encrypts_at_rest=False,
        signs_values=False,
        cacheable=True,
    )


class EnvSecretOperations:
    """Read + list from `os.environ`. Read-only by design."""

    def __init__(self, *, upper: bool = True, env: "Mapping[str, str] | None" = None) -> None:
        self._upper = upper
        self._env = env if env is not None else os.environ
        self._lock = threading.Lock()

    def _key(self, reference: SecretReference) -> str:
        return reference.path.upper() if self._upper else reference.path

    def _value(self, reference: SecretReference) -> SecretValue:
        key = self._key(reference)
        if reference.path not in self._env and key not in self._env:
            raise SecretIntegrityException(
                f"env var not set: {key!r}",
            )
        actual_key = reference.path if reference.path in self._env else key
        raw = self._env[actual_key]
        version = SecretVersion(number="v0", created_at=None)
        metadata = SecretMetadata(
            reference=reference,
            version=version,
            backend=SecretBackend.ENV,
            created_at=datetime.now(tz=timezone.utc),
            expires_at=None,
            tags={"env": actual_key},
        )
        return SecretValue(plaintext=raw.encode("utf-8"), metadata=metadata)

    def get(self, reference: SecretReference) -> SecretValue:
        with self._lock:
            return self._value(reference)

    def get_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        if reference.version_selector.kind is not SecretVersionSelectorKind.STATIC:
            raise SecretConfigurationException(
                "env: get_version only supports STATIC selector with v0",
            )
        with self._lock:
            return self._value(reference)

    def get_metadata(self, reference: SecretReference) -> SecretMetadata:
        return self.get(reference).metadata

    def exists(self, reference: SecretReference) -> bool:
        with self._lock:
            return reference.path in self._env or (
                self._upper and reference.path.upper() in self._env
            )

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        with self._lock:
            env_keys = sorted(self._env.keys())
        if prefix is None:
            return [
                SecretReference(provider="env", path=key)
                for key in env_keys
            ]
        return [
            SecretReference(provider="env", path=key)
            for key in env_keys
            if key.startswith(prefix)
        ]


class EnvSecretProviderFactory:
    """`SecretProviderFactory` for the env-var backend."""

    def __init__(
        self,
        name: str = "env",
        version: str = "0.2.0",
        *,
        upper: bool = True,
    ) -> None:
        self._name = name
        self._version = version
        self._upper = upper

    @property
    def name(self) -> str:
        return self._name

    @property
    def backend(self) -> SecretBackend:
        return SecretBackend.ENV

    @property
    def capability(self) -> SecretCapability:
        return _env_capability()

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
        operations = EnvSecretOperations(upper=self._upper)
        return _EnvSession(
            configuration=configuration,
            descriptor=self.descriptor(),
            operations=operations,
        )


class _EnvSession:
    __slots__ = (
        "_configuration",
        "_descriptor",
        "_operations",
        "_closed",
    )

    def __init__(
        self,
        *,
        configuration: SecretProviderConfiguration,
        descriptor: SecretProviderDescriptor,
        operations: SecretOperations,
    ) -> None:
        self._configuration = configuration
        self._descriptor = descriptor
        self._operations = operations
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
    def writer(self):
        return None

    @property
    def deletable(self):
        return None

    @property
    def snapshot_manager(self):
        # No rotation events for a read-only backend; provide a fresh
        # manager so the framework can call methods without crashing.
        from atlas_richie.secret.snapshot import SecretSnapshotManager
        return SecretSnapshotManager()

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True


__all__ = [
    "EnvSecretProviderFactory",
    "EnvSecretOperations",
]


_ = (SecretListable, SecretProviderSession)
