"""默认 `SecretBootstrapClient` — 委托给 `SecretResolver`。

中文
----
对位 Java `SecretBootstrapClient` 的默认实现。

`ResolverBackedBootstrapClient` 用 `SecretRegistry.sessions` 中的
provider 串接 `DefaultSecretResolver`,按 `binding.reference.provider`
路由 resolve;`required_when` 策略由 `SecretPropertyPolicy` 决定
STARTUP 缺失是否 raise。

设计:

- **policy 优先**:binding 自带 `required_when` 与 policy 的
  `default_required_when` 比较;binding 自身非空时 binding 优先
- **并行度**:`max_parallel_resolves` 默认 1,因为多数 backend 的
  token endpoint 不支持并发调用

English
--------
Default `SecretBootstrapClient` backed by `SecretResolver`.
Mirrors the Java default bootstrap client. Resolves each binding
through the registry's sessions; respects the policy's
`default_required_when` and `tolerate_missing` flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from atlas_richie.secret.bootstrap.catalog import RequiredWhen
from atlas_richie.secret.bootstrap.policy import SecretPropertyPolicy
from atlas_richie.secret.bootstrap.spi import (
    SecretBootstrapClient,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
)
from atlas_richie.secret.errors import SecretBootstrapException
from atlas_richie.secret.registry.secret_registry import SecretRegistry
from atlas_richie.secret.value import SecretValue

if TYPE_CHECKING:
    from atlas_richie.secret.resolver import DefaultSecretResolver


class ResolverBackedBootstrapClient:
    """Default bootstrap client that delegates to a `DefaultSecretResolver`."""

    def __init__(
        self,
        *,
        registry: SecretRegistry,
        policy: SecretPropertyPolicy | None = None,
        resolver: "DefaultSecretResolver | None" = None,
    ) -> None:
        self._registry = registry
        self._policy = policy or SecretPropertyPolicy()
        self._resolver = resolver

    def bootstrap(
        self,
        request: SecretBootstrapRequest,
        context: SecretBootstrapContext,
    ) -> SecretBootstrapResult:
        from atlas_richie.secret.resolver import DefaultSecretResolver

        resolver = self._resolver or self._build_resolver()
        resolved: dict[str, SecretValue] = {}
        missing: list[str] = []
        started_at = context.now or datetime.now(tz=timezone.utc)
        for binding in request.catalog.bindings:
            effective = binding.required_when or self._policy.default_required_when
            try:
                value = resolver.resolve(binding.reference)
            except Exception as error:  # noqa: BLE001
                if effective is RequiredWhen.STARTUP and not self._policy.tolerate_missing:
                    raise SecretBootstrapException(
                        f"required binding {binding.name!r} failed: {error}",
                    ) from error
                missing.append(binding.name)
                continue
            resolved[binding.name] = value
        finished_at = datetime.now(tz=timezone.utc)
        return SecretBootstrapResult(
            resolved=resolved,
            missing=tuple(missing),
            started_at=started_at,
            finished_at=finished_at,
        )

    def _build_resolver(self) -> "DefaultSecretResolver":
        from atlas_richie.secret.resolver import DefaultSecretResolver

        return DefaultSecretResolver(
            providers=dict(self._registry.sessions()),
            snapshot_manager=self._registry.shared_snapshot_manager(),
        )


__all__ = ["ResolverBackedBootstrapClient"]


_ = (Mapping, SecretBootstrapClient)
