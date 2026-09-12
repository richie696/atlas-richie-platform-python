"""Secret 启动期状态与 topology。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.SecretBootstrapState` /
`SecretProviderTopology`。

- `SecretBootstrapState` — StrEnum,bootstrap 生命周期状态:
  - `PENDING` — 还未 bootstrap
  - `IN_PROGRESS` — bootstrap 进行中
  - `READY` — 启动期注入完成(可继续 lazy)
  - `FAILED` — 启动期失败(可选 partial 状态)
  - `CLOSED` — 应用已 close
- `SecretProviderTopology` — frozen dataclass,描述当前所有活跃
  provider 的拓扑(name + backend + 已注册 binding 数)。
- `SecretBootstrapSnapshot` — frozen dataclass,bootstrap 当前状态
  快照(state + topology + 上次 result + last_updated_at)。

`SecretBootstrapState` 是诊断 + 健康检查用的 enum,不参与逻辑分支
判断(facade 层不写 `if state == READY` 之类的硬编码 — 用 provider
presence / binding 缺失来表达)。

English
--------
Secret bootstrap state + provider topology. Mirrors the Java
`SecretBootstrapState` / `SecretProviderTopology`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from atlas_richie.secret.bootstrap.spi import SecretBootstrapResult
from atlas_richie.secret.metadata import SecretBackend


class SecretBootstrapState(StrEnum):
    """Lifecycle state of the bootstrap subsystem."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    FAILED = "failed"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class SecretProviderTopology:
    """Snapshot of all providers currently registered in the topology.

    Attributes:
        providers: Mapping from provider name to backend family.
        binding_counts: Mapping from provider name to the number of
            `SecretBinding`s whose `reference.provider` matches.
    """

    providers: Mapping[str, SecretBackend]
    binding_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class SecretBootstrapSnapshot:
    """Current snapshot of the bootstrap subsystem.

    Attributes:
        state: Lifecycle state.
        topology: Active provider topology.
        last_result: Most recent `SecretBootstrapResult`, or ``None``
            if bootstrap has not yet run.
        last_updated_at: UTC time the snapshot was last refreshed.
    """

    state: SecretBootstrapState
    topology: SecretProviderTopology
    last_result: SecretBootstrapResult | None
    last_updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


__all__ = [
    "SecretBootstrapState",
    "SecretProviderTopology",
    "SecretBootstrapSnapshot",
]
