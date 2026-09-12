"""Secret provider 描述符 — provider 的元数据。

中文
----
对位 Java `cn.richie696.component.secret.api.provider.SecretProviderDescriptor`。

`SecretProviderDescriptor` 描述一个已注册 provider 的元数据(名称 /
backend 类型 / 能力)。`SecretRegistry` 持有 `provider -> descriptor` 映射,
facade 用它做能力探测。

设计:

- **frozen dataclass**:`name` + `backend` + `capability` + `version`,
  不可变,可在外部用作 cache key。
- **version 字符串**:provider 自己的版本(`"redis-1.2.0"` /
  `"vault-3.0.1"`),framework 不强解释。

English
--------
Secret provider descriptor. Mirrors the Java
`SecretProviderDescriptor`. Frozen dataclass with name / backend /
capability / version.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_richie.secret.metadata import SecretBackend, SecretCapability


@dataclass(frozen=True, slots=True)
class SecretProviderDescriptor:
    """Static metadata for a registered secret provider.

    Attributes:
        name: Provider name (matches `SecretReference.provider`).
        backend: Backend implementation family.
        capability: Static capability of this backend instance.
        version: Backend-specific version string.
    """

    name: str
    backend: SecretBackend
    capability: SecretCapability
    version: str = "0.0.0"


__all__ = ["SecretProviderDescriptor"]
