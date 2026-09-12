"""Secret 引用与版本模型。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretReference` /
`SecretVersion` / `SecretVersionSelector`。

- `SecretReference` — 用 `(provider, path)` 标识一个 secret 实例,
  `provider` 是 backend 名称(在 provider descriptor 中定义),`path` 是
  backend 内的逻辑路径(Redis 用 `app:db:password` 形式,Env 用
  `APP_DB_PASSWORD` 形式,File 用 `/etc/secrets/app/db.password` 形式)。
- `SecretVersion` — frozen dataclass,标识一个具体的 secret 版本。包含
  版本号字符串 + 可选的时间戳(由 backend 提供)。
- `SecretVersionSelector` — 解析"哪个版本"的策略枚举:
  - `LATEST` — 总是最新
  - `STATIC` — 锁死到具体版本号
  - `PINNED_AT_TIME` — 在指定 UTC 时间戳处"看"的最新版本(用于回放)

`SecretReference.with_version(selector)` 是 builder 模式入口,返回新的
不可变 `SecretReference`。`equals` / `hash` 基于值,所以同一引用可作为
dict key / set element。

English
--------
Secret reference and version model. Mirrors the Java
`cn.richie696.component.secret.api.SecretReference` /
`SecretVersion` / `SecretVersionSelector`. `SecretReference` is a
frozen dataclass (immutable + hashable) supporting the builder-style
`.with_version(...)` chain.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum


class SecretVersionSelectorKind(Enum):
    """Resolution strategy for which version of a secret to read."""

    LATEST = "latest"
    STATIC = "static"
    PINNED_AT_TIME = "pinned_at_time"


@dataclass(frozen=True, slots=True)
class SecretVersion:
    """Concrete version identifier returned by a backend.

    Attributes:
        number: Backend-defined version string. Most backends use a
            monotonically increasing integer rendered as a string
            (e.g. ``"v1"`` / ``"42"``); some (e.g. AWS Secrets
            Manager) use UUIDs.
        created_at: Optional UTC creation time as reported by the
            backend. ``None`` means the backend does not track version
            timestamps.
    """

    number: str
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SecretVersionSelector:
    """Selector describing which version of a secret to read.

    Attributes:
        kind: One of `LATEST` / `STATIC` / `PINNED_AT_TIME`.
        static_version: Required when `kind == STATIC`; concrete
            `SecretVersion` to lock onto.
        pinned_at: Required when `kind == PINNED_AT_TIME`; UTC time
            to evaluate "the latest version that existed at that
            time". Backend resolves this at read time.
    """

    kind: SecretVersionSelectorKind
    static_version: SecretVersion | None = None
    pinned_at: datetime | None = None

    @staticmethod
    def latest() -> "SecretVersionSelector":
        """Always the most recent version."""
        return SecretVersionSelector(kind=SecretVersionSelectorKind.LATEST)

    @staticmethod
    def of_static(version: SecretVersion) -> "SecretVersionSelector":
        """Pin to a specific concrete version."""
        return SecretVersionSelector(
            kind=SecretVersionSelectorKind.STATIC,
            static_version=version,
        )

    @staticmethod
    def pinned_at(when: datetime) -> "SecretVersionSelector":
        """Read the latest version that existed at `when` (UTC)."""
        return SecretVersionSelector(
            kind=SecretVersionSelectorKind.PINNED_AT_TIME,
            pinned_at=when,
        )


@dataclass(frozen=True, slots=True)
class SecretReference:
    """Canonical reference to a secret instance.

    Attributes:
        provider: Provider name as registered in the provider
            descriptor (e.g. ``"redis-prod"``, ``"vault-main"``).
        path: Backend-defined logical path of the secret.
        version_selector: Strategy for choosing which version to read.
            Defaults to `latest()`.
        tags: Optional caller-side labels used for observability
            (audit logs, traces). Not used to address the secret.
    """

    provider: str
    path: str
    version_selector: SecretVersionSelector = field(
        default_factory=SecretVersionSelector.latest,
    )
    tags: frozenset[tuple[str, str]] = field(default_factory=frozenset)

    def with_version(self, selector: SecretVersionSelector) -> "SecretReference":
        """Builder-style fluent API: return a new reference with the
        given version selector.
        """
        return replace(self, version_selector=selector)

    def with_tag(self, key: str, value: str) -> "SecretReference":
        """Return a new reference with the additional tag set.

        Tags are pure observability metadata; they do not affect
        backend-side secret resolution.
        """
        return replace(self, tags=self.tags | {(key, value)})


__all__ = [
    "SecretVersionSelectorKind",
    "SecretVersion",
    "SecretVersionSelector",
    "SecretReference",
]
