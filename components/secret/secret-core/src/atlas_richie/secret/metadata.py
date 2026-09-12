"""Secret 元数据、backend 枚举、capability 描述。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretMetadata` /
`SecretBackend` / `SecretCapability`。

- `SecretBackend` — StrEnum,标识 secret 的物理存储后端(in_memory / env /
  file / redis / vault / openbao / pkcs11 / aws / azure / gcp / aliyun /
  tencent / huawei / baidu / volcengine / oci / ibm / kmip / barbican)。
  Python 端只暴露 framework 关心的 4 个本地 backend;远程 backend 留作
  `secret-redis` 等独立 wheel 实现。
- `SecretCapability` — frozen dataclass,描述一个 secret backend 提供的
  能力(读 / 写 / 旋转 / 列出 / 加密存储 / 签名)。Provider 在注册时
  声明自己的 capability,facade 据此决定能否满足调用方请求。
- `SecretMetadata` — frozen dataclass,描述一个 secret 实例的元数据
  (路径 / 版本 / 创建时间 / 过期时间 / backend / 标签)。

设计:用 `from __future__ import annotations` 把 `SecretReference` /
`SecretVersion` 的引用全部转为字符串,运行时由 `typing.get_type_hints`
解析,避免 `metadata ↔ reference` 的循环 import。

English
--------
Secret metadata, backend enum, capability descriptor.

Mirrors the Java `cn.richie696.component.secret.api.SecretMetadata` /
`SecretBackend` / `SecretCapability`. All forward references to
`SecretReference` / `SecretVersion` are string-typed to avoid the
metadata ↔ reference cycle at import time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SecretBackend(StrEnum):
    """Stable identifier for a secret's physical storage backend.

    Mirrors the Java `SecretBackend` enum. Local members are
    implemented in this package; remote members are placeholders that
    remote backends can use as their `SecretProviderDescriptor.backend`
    value.
    """

    IN_MEMORY = "in_memory"
    ENV = "env"
    FILE = "file"
    REDIS = "redis"
    VAULT = "vault"
    OPENBAO = "openbao"
    PKCS11 = "pkcs11"
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    ALIYUN = "aliyun"
    TENCENT = "tencent"
    HUAWEI = "huawei"
    BAIDU = "baidu"
    VOLCENGINE = "volcengine"
    OCI = "oci"
    IBM_KEY_PROTECT = "ibm_key_protect"
    KMIP = "kmip"
    BARBICAN = "barbican"


@dataclass(frozen=True, slots=True)
class SecretCapability:
    """Static capability description for a secret backend.

    Attributes:
        can_read: Backend supports synchronous secret reads.
        can_write: Backend supports secret creation / update / rotation.
        can_rotate: Backend supports atomic version rotation.
        can_list: Backend supports listing known secret references.
        encrypts_at_rest: Backend persists ciphertext rather than plaintext.
        signs_values: Backend attaches a signature to each value.
        cacheable: Resolver may keep a local cache of read results.
    """

    can_read: bool
    can_write: bool
    can_rotate: bool
    can_list: bool
    encrypts_at_rest: bool
    signs_values: bool
    cacheable: bool


@dataclass(frozen=True, slots=True)
class SecretMetadata:
    """Metadata attached to a secret value.

    Attributes:
        reference: Canonical reference to the secret.
        version: Concrete version returned by the backend.
        backend: Backend that produced this secret value.
        created_at: UTC creation time as reported by the backend.
        expires_at: Optional UTC expiry. ``None`` means the backend
            does not track expiry or the secret is non-expiring.
        tags: Free-form backend-defined labels (e.g. ``env=prod``).
    """

    reference: "SecretReference"
    version: "SecretVersion"
    backend: SecretBackend
    created_at: datetime
    expires_at: datetime | None
    tags: Mapping[str, str]


__all__ = [
    "SecretBackend",
    "SecretCapability",
    "SecretMetadata",
]
