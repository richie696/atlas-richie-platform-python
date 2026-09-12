"""Secret provider 配置契约。

中文
----
对位 Java `cn.richie696.component.secret.api.provider.SecretProviderConfiguration`。

`SecretProviderConfiguration` 是 backend 的不可变配置。`SecretProviderFactory`
用它构造 backend 客户端;`SecretProviderDescriptor` 在注册时携带它。

设计:

- **frozen dataclass**:不可变,线程安全,可作 cache key。
- **泛型化**:`parameters: Mapping[str, str]` 容纳 backend 特定参数(如
  Redis URL、Vault token、PKCS#11 slot)。框架不解释具体键,由 backend
  factory 解析。
- **不强制必填**:`timeout_seconds` / `retries` 提供合理默认值。

English
--------
Secret provider configuration contract. Mirrors the Java
`SecretProviderConfiguration`. The dataclass is frozen, so it is
immutable and safe to share across threads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecretProviderConfiguration:
    """Immutable configuration handed to a `SecretProviderFactory`.

    Attributes:
        name: Provider name used in `SecretReference.provider`
            (e.g. ``"redis-prod"``).
        parameters: Backend-specific parameters (URL, token, slot,
            region, ...). Keys are backend-defined; the framework
            does not interpret them.
        timeout_seconds: Maximum wall-clock time for a single
            backend call. ``0`` means no timeout.
        retries: Number of retry attempts for transient backend
            failures. ``0`` means no retry.
        namespace: Optional namespace prefix used for keying. Some
            backends (e.g. Redis) prepend this to the secret path.
    """

    name: str
    parameters: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 0.0
    retries: int = 0
    namespace: str = ""


__all__ = ["SecretProviderConfiguration"]
