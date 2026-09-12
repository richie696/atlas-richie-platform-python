"""Secret 启动期 property 策略。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.SecretPropertyPolicy` /
`BootstrapSecretProperties`。

`SecretPropertyPolicy` — frozen dataclass,定义 bootstrap 期解析 binding
时的策略:

- `default_required_when` — 当 binding 没显式标 `required_when` 时
  使用;默认 `RequiredWhen.STARTUP`。
- `tolerate_missing` — 缺 binding 时是否 raise;True 表示 missing
  binding 写入 `result.missing` 但不抛。
- `max_parallel_resolves` — 并发 resolve 数;默认 1(sequential,
  因为多数 backend 不支持并发 token 拉取)。
- `resolve_timeout_seconds` — 单个 binding resolve 的超时;0 不超时。
- `fail_on_unsupported_exposure` — 当 binding 的 exposure 不可由
  bootstrap 阶段实际注入时是否 raise。

`BootstrapSecretProperties` — frozen dataclass,bootstrap 启动器(后
面 `AtlasSecretEnvironmentPostProcessor`)读入的配置。`parameters` 容
纳 backend 特定的 URL / token 等。

English
--------
Secret property policy. Mirrors the Java `SecretPropertyPolicy` /
`BootstrapSecretProperties`. The policy is the runtime-tunable
default for `required_when` / `tolerate_missing` / parallelism /
per-binding timeout; the properties are the boot-time configuration
read by the post-processor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from atlas_richie.secret.bootstrap.catalog import RequiredWhen


@dataclass(frozen=True, slots=True)
class SecretPropertyPolicy:
    """Resolution policy applied to each binding during bootstrap.

    Attributes:
        default_required_when: Fallback when a binding does not
            specify its own `required_when`.
        tolerate_missing: When ``True``, missing bindings are
            recorded in `result.missing` instead of raising.
        max_parallel_resolves: Number of concurrent resolve calls.
            Backend token endpoints usually cap concurrency; 1 is
            the safe default.
        resolve_timeout_seconds: Per-binding resolve timeout. ``0``
            means no timeout.
        fail_on_unsupported_exposure: When ``True``, a binding with
            an exposure that the bootstrapper cannot fulfill raises
            `SecretBootstrapException`. ``False`` silently records
            the exposure as unresolved.
    """

    default_required_when: RequiredWhen = RequiredWhen.STARTUP
    tolerate_missing: bool = False
    max_parallel_resolves: int = 1
    resolve_timeout_seconds: float = 0.0
    fail_on_unsupported_exposure: bool = True


@dataclass(frozen=True, slots=True)
class BootstrapSecretProperties:
    """Boot-time configuration read by `AtlasSecretEnvironmentPostProcessor`.

    Attributes:
        active: Whether bootstrap is enabled. ``False`` makes the
            post-processor a no-op (useful for tests).
        policy: Default policy applied to all bindings.
        parameters: Backend-specific parameters (URL, token, region).
        catalog_paths: Optional list of catalog source identifiers.
            The default in-memory loader does not consume these;
            the YAML / TOML loader is an extension point.
    """

    active: bool = True
    policy: SecretPropertyPolicy = field(default_factory=SecretPropertyPolicy)
    parameters: Mapping[str, str] = field(default_factory=dict)
    catalog_paths: tuple[str, ...] = ()


__all__ = [
    "SecretPropertyPolicy",
    "BootstrapSecretProperties",
]
