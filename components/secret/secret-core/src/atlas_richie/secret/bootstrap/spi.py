"""Secret 启动期注入 SPI。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.spi.*`(6 个 class):
`SecretBootstrapClient` / `SecretBootstrapContext` /
`SecretBootstrapProviderFactory` / `SecretBootstrapRequest` /
`SecretBootstrapResult` / `SecretProviderType`。

- `SecretProviderType` — StrEnum,标记 provider 类型(local / remote /
  transient / ephemeral)。Bootstrap 根据类型选择 discover 策略。
- `SecretBootstrapRequest` — frozen dataclass,一次 bootstrap 调用的入参
  (`catalog` + `environment` profile + `policy`)。
- `SecretBootstrapResult` — frozen dataclass,bootstrap 输出(每个 binding
  的 resolved value / metadata / 是否 missing)。
- `SecretBootstrapContext` — Protocol,framework 注入到 SPI 中的"环境"
  (current time / process / environment profile / signal handler)。
- `SecretBootstrapClient` — Protocol,具体实现负责把 catalog 转成实际
  resolved values(`resolver.resolve(binding.reference)`)。
- `SecretBootstrapProviderFactory` — Protocol,构造 `SecretBootstrapClient`
  的工厂(framework 用它按 `SecretProviderType` 路由到不同 client)。

设计:与 Java 一致,binding 在 startup 阶段全部解析完,缺失的
`required_when=STARTUP` binding 立即抛 `SecretBootstrapException`,
`required_when=LAZY` 标记成 missing 但不中断。

English
--------
Secret bootstrap SPI. Mirrors the Java `SecretBootstrapClient` /
`SecretBootstrapContext` / `SecretBootstrapProviderFactory` /
`SecretBootstrapRequest` / `SecretBootstrapResult` /
`SecretProviderType`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from atlas_richie.secret.bootstrap.catalog import SecretBindingCatalog
from atlas_richie.secret.value import SecretValue


class SecretProviderType(StrEnum):
    """Classification of a provider for bootstrap discovery."""

    LOCAL = "local"
    REMOTE = "remote"
    TRANSIENT = "transient"
    EPHEMERAL = "ephemeral"


@dataclass(frozen=True, slots=True)
class SecretBootstrapRequest:
    """Bootstrap call input.

    Attributes:
        catalog: The binding catalog to resolve.
        environment: Optional environment profile (e.g. ``"prod"``,
            ``"staging"``). Used to filter `SecretBindingCatalogSet`
            overlays.
        required_when_override: Optional override of
            `RequiredWhen` policy. If set, missing bindings that
            match the policy are tolerated; if not, the request
            uses each binding's own `required_when`.
    """

    catalog: SecretBindingCatalog
    environment: str = "default"
    required_when_override: "str | None" = None


@dataclass(frozen=True, slots=True)
class SecretBootstrapResult:
    """Bootstrap call output.

    Attributes:
        resolved: Mapping from binding name to the resolved
            `SecretValue`.
        missing: Tuple of binding names that could not be resolved
            within the active `RequiredWhen` policy.
        started_at: UTC time when bootstrap began.
        finished_at: UTC time when bootstrap completed.
    """

    resolved: Mapping[str, SecretValue]
    missing: tuple[str, ...]
    started_at: datetime
    finished_at: datetime


@runtime_checkable
class SecretBootstrapContext(Protocol):
    """Framework-injected environment for bootstrap."""

    @property
    def now(self) -> datetime:
        ...

    @property
    def environment(self) -> str:
        ...

    @property
    def process_id(self) -> int:
        ...


class DefaultBootstrapContext:
    """Default in-memory bootstrap context."""

    def __init__(
        self,
        *,
        environment: str = "default",
        now: datetime | None = None,
        process_id: int | None = None,
    ) -> None:
        from datetime import datetime as _dt, timezone

        self._now = now or _dt.now(tz=timezone.utc)
        self._environment = environment
        self._process_id = process_id if process_id is not None else 0

    @property
    def now(self) -> datetime:
        return self._now

    @property
    def environment(self) -> str:
        return self._environment

    @property
    def process_id(self) -> int:
        return self._process_id


@runtime_checkable
class SecretBootstrapClient(Protocol):
    """Resolves a `SecretBootstrapRequest` to a `SecretBootstrapResult`."""

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        ...


@runtime_checkable
class SecretBootstrapProviderFactory(Protocol):
    """Constructs `SecretBootstrapClient`s per `SecretProviderType`."""

    def client_for(self, provider_type: SecretProviderType) -> SecretBootstrapClient:
        ...


__all__ = [
    "SecretProviderType",
    "SecretBootstrapRequest",
    "SecretBootstrapResult",
    "SecretBootstrapContext",
    "DefaultBootstrapContext",
    "SecretBootstrapClient",
    "SecretBootstrapProviderFactory",
]


_ = (field,)
