"""Secret testkit — 协议夹具,供跨包 conformance / E2E 测试使用。

中文
----
对位 Java `atlas-richie-secret-testkit` 子包(`McpSecretFixtures` /
`McpSecretEnvironmentStub` / ...),Python 端目前提供:

- `InMemorySecretFixture` — 工厂,构造一个带 InMemory backend 的
  `GlobalSecretManager`,返回 `GlobalSecret` facade 包装。给
  conformance 测试使用。
- `StubSecretCallback` — 计数 callback,记录每次 read / write /
  rotate / failure 的引用,断言用。
- `RecordingSnapshotListener` — 记录所有 `SecretSnapshotChangedEvent`,
  给 E2E 验证轮转事件 fan-out 用。

设计:与 Java testkit 一样,只放"协议夹具",不放"业务测试"
(后者留在 `components/secret/secret-core/tests/`)。

English
--------
Secret testkit sub-package. Re-exports protocol fixtures used by
cross-package conformance / E2E tests. The Python side mirrors the
Java `atlas-richie-secret-testkit` sub-module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from atlas_richie.secret.bootstrap.catalog import SecretBindingCatalog
from atlas_richie.secret.callback import SecretCallback
from atlas_richie.secret.local.in_memory import InMemorySecretProviderFactory
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.provider.configuration import SecretProviderConfiguration
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotChangedEvent, SecretSnapshotListener
from atlas_richie.secret.testkit.bundle import ProviderBundle
from atlas_richie.secret.value import SecretValue


@dataclass(slots=True)
class StubSecretCallback:
    """`SecretCallback` that records every fired method.

    Tests assert on `reads` / `writes` / `rotates` / `failures`
    lists after driving a `GlobalSecret` through specific flows.
    """

    reads: list[tuple[SecretReference, SecretValue]] = field(default_factory=list)
    writes: list[tuple[SecretReference, SecretValue]] = field(default_factory=list)
    rotates: list[tuple[SecretReference, SecretValue | None, SecretValue]] = field(
        default_factory=list,
    )
    failures: list[tuple[SecretReference, BaseException]] = field(
        default_factory=list,
    )
    metadatas: list[tuple[SecretReference, SecretMetadata]] = field(
        default_factory=list,
    )

    def on_read(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        self.reads.append((reference, value))

    def on_write(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        self.writes.append((reference, value))

    def on_rotate(
        self,
        reference: SecretReference,
        previous: SecretValue | None,
        current: SecretValue,
    ) -> None:
        self.rotates.append((reference, previous, current))

    def on_resolve_failure(
        self,
        reference: SecretReference,
        error: BaseException,
    ) -> None:
        self.failures.append((reference, error))

    def on_metadata(
        self,
        reference: SecretReference,
        metadata: SecretMetadata,
    ) -> None:
        self.metadatas.append((reference, metadata))


@dataclass(slots=True)
class RecordingSnapshotListener:
    """`SecretSnapshotListener` that captures every event for assertions."""

    events: list[SecretSnapshotChangedEvent] = field(default_factory=list)

    def on_snapshot_changed(self, event: SecretSnapshotChangedEvent) -> None:
        self.events.append(event)


def in_memory_fixture(
    *,
    name: str = "test",
    version: str = "test-0.0.0",
    configuration: SecretProviderConfiguration | None = None,
) -> tuple[InMemorySecretProviderFactory, "ProviderBundle"]:
    """Build an in-memory backend fixture plus a configuration.

    Returns `(factory, bundle)` so tests can either install via the
    factory or use the bundle directly.
    """
    from atlas_richie.secret.testkit.bundle import ProviderBundle

    factory = InMemorySecretProviderFactory(name=name, version=version)
    config = configuration or SecretProviderConfiguration(name=name)
    bundle = ProviderBundle(factory=factory, configuration=config)
    return factory, bundle


__all__ = [
    "StubSecretCallback",
    "RecordingSnapshotListener",
    "ProviderBundle",
    "in_memory_fixture",
]


_ = (SecretVersion, Iterable, SecretBindingCatalog)
