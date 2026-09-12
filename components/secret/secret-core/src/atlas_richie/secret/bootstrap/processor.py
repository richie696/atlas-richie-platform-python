"""Secret 环境启动期后置处理器。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.AtlasSecretEnvironmentPostProcessor`。

`AtlasSecretEnvironmentPostProcessor` 是 bootstrap 子系统的入口。它在
应用启动早期(在任何用户代码读 `os.environ` 之前)运行:

1. 加载 `BootstrapSecretProperties`(`active=False` 时直接跳过)。
2. 加载 `SecretBindingCatalog`(由 `properties.catalog_paths` 指示的
   loader 拉取;默认空 = 使用 `SecretRegistry` 已注册的 catalogs)。
3. 用 `SecretBootstrapClient` 解析每个 binding。
4. 按 binding.exposure 注入到对应介质(env / file / argv)。
5. 标记 `SecretBootstrapState = READY`,记录 `last_result` 到
   `SecretRegistry`。

设计:用 `SecretBootstrapClient` 抽象(而非直接在 processor 里调
`SecretResolver.resolve`),让测试可以用 mock client 替代真实 client。
真实 client 是 `ResolverBackedBootstrapClient`(在
`__init__.py` 中提供),内部委托给 `DefaultSecretResolver`。

English
--------
Secret environment post-processor. Mirrors the Java
`AtlasSecretEnvironmentPostProcessor`. The post-processor is the
bootstrap subsystem's entry point; it runs before any user code
touches `os.environ`, and applies each binding to its target
exposure (env / file / argv).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from atlas_richie.secret.bootstrap.catalog import (
    SecretBinding,
    SecretBindingCatalog,
    SecretBindingCatalogSet,
    SecretExposure,
)
from atlas_richie.secret.bootstrap.policy import BootstrapSecretProperties
from atlas_richie.secret.bootstrap.spi import (
    DefaultBootstrapContext,
    SecretBootstrapContext,
    SecretBootstrapRequest,
    SecretBootstrapResult,
    SecretProviderType,
)
from atlas_richie.secret.bootstrap.state import (
    SecretBootstrapSnapshot,
    SecretBootstrapState,
    SecretProviderTopology,
)
from atlas_richie.secret.errors import SecretBootstrapException
from atlas_richie.secret.registry.secret_registry import SecretRegistry
from atlas_richie.secret.value import SecretValue


class AtlasSecretEnvironmentPostProcessor:
    """Apply `SecretBindingCatalog` to the process environment.

    The post-processor is the only public entry point of the
    bootstrap subsystem; the rest (`SecretBootstrapClient`,
    `SecretBootstrapProviderFactory`, `SecretBootstrapRequest` /
    `SecretBootstrapResult`) is the in-process SPI used by tests
    and the default client.
    """

    def __init__(
        self,
        *,
        registry: SecretRegistry,
        client_factory: "callable[[SecretProviderType], object] | None" = None,
        properties: BootstrapSecretProperties | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._registry = registry
        self._client_factory = client_factory
        self._properties = properties or BootstrapSecretProperties()
        self._logger = logger or logging.getLogger(
            "atlas_richie.secret.bootstrap",
        )
        self._state = SecretBootstrapState.PENDING
        self._last_result: SecretBootstrapResult | None = None
        self._last_catalog: SecretBindingCatalog | None = None

    @property
    def state(self) -> SecretBootstrapState:
        return self._state

    @property
    def last_result(self) -> SecretBootstrapResult | None:
        return self._last_result

    def post_process(
        self,
        catalog_set: SecretBindingCatalogSet | SecretBindingCatalog | None = None,
        context: SecretBootstrapContext | None = None,
    ) -> SecretBootstrapSnapshot:
        """Run the bootstrap. Returns the final snapshot.

        When `properties.active` is ``False``, this is a no-op that
        returns a `PENDING` snapshot.
        """
        if not self._properties.active:
            self._logger.info("secret bootstrap is inactive; skipping")
            return self._snapshot_now(SecretBootstrapState.PENDING)

        ctx = context or DefaultBootstrapContext()
        self._state = SecretBootstrapState.IN_PROGRESS
        catalog = self._resolve_catalog(catalog_set, ctx)
        request = SecretBootstrapRequest(
            catalog=catalog,
            environment=ctx.environment,
        )
        client = self._client_for(request)
        try:
            result = client.bootstrap(request, ctx)
        except Exception as error:
            self._state = SecretBootstrapState.FAILED
            self._logger.exception("secret bootstrap failed: %s", error)
            raise

        self._apply_exposures(result, catalog, ctx)
        self._state = SecretBootstrapState.READY
        self._last_result = result
        self._logger.info(
            "secret bootstrap ready: %d resolved, %d missing",
            len(result.resolved),
            len(result.missing),
        )
        return self._snapshot_now(SecretBootstrapState.READY)

    def snapshot(self) -> SecretBootstrapSnapshot:
        """Return the latest snapshot without re-running bootstrap."""
        return self._snapshot_now(self._state)

    # --- Internal helpers ------------------------------------------------

    def _resolve_catalog(
        self,
        catalog_set: SecretBindingCatalogSet | SecretBindingCatalog | None,
        context: SecretBootstrapContext,
    ) -> SecretBindingCatalog:
        if catalog_set is None:
            registered = self._registry.catalogs()
            if not registered:
                resolved = SecretBindingCatalog(name="<empty>")
                self._last_catalog = resolved
                return resolved
            resolved = SecretBindingCatalogSet(catalogs=tuple(registered)).merged()
            self._last_catalog = resolved
            return resolved
        if isinstance(catalog_set, SecretBindingCatalog):
            self._last_catalog = catalog_set
            return catalog_set
        resolved = catalog_set.merged()
        self._last_catalog = resolved
        return resolved

    def _client_for(self, request: SecretBootstrapRequest):
        if self._client_factory is None:
            from atlas_richie.secret.bootstrap.default_client import (
                ResolverBackedBootstrapClient,
            )
            return ResolverBackedBootstrapClient(
                registry=self._registry,
                policy=self._properties.policy,
            )
        return self._client_factory(SecretProviderType.REMOTE)

    def _apply_exposures(
        self,
        result: SecretBootstrapResult,
        catalog: SecretBindingCatalog,
        context: SecretBootstrapContext,
    ) -> None:
        for name, value in result.resolved.items():
            binding = self._find_binding(catalog, name)
            if binding is None:
                continue
            self._apply_one(binding, value, context)

    def _find_binding(
        self,
        catalog: SecretBindingCatalog,
        name: str,
    ) -> SecretBinding | None:
        for binding in catalog.bindings:
            if binding.name == name:
                return binding
        return None

    def _apply_one(
        self,
        binding: SecretBinding,
        value: SecretValue,
        context: SecretBootstrapContext,
    ) -> None:
        if binding.exposure is SecretExposure.ENV:
            os.environ[binding.property_name()] = value.as_str()
            return
        if binding.exposure is SecretExposure.FILE:
            target = Path(binding.property_name())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value.plaintext)
            return
        if binding.exposure is SecretExposure.ARGV:
            # argv exposure is rare; the application must read the
            # secret via a dedicated loader. We only mark the state.
            self._logger.info(
                "argv exposure for binding %r is acknowledged but not applied",
                binding.name,
            )
            return
        if binding.exposure is SecretExposure.SERVICE_BUS:
            self._logger.info(
                "service_bus exposure for binding %r is acknowledged; "
                "publish not implemented in framework",
                binding.name,
            )
            return
        if self._properties.policy.fail_on_unsupported_exposure:
            raise SecretBootstrapException(
                f"unsupported exposure for binding {binding.name!r}: "
                f"{binding.exposure!r}",
            )

    def _snapshot_now(self, state: SecretBootstrapState) -> SecretBootstrapSnapshot:
        topology = SecretProviderTopology(
            providers={
                name: session.descriptor.backend
                for name, session in self._registry.sessions().items()
            },
            binding_counts={
                name: 0 for name in self._registry.sessions()
            },
        )
        return SecretBootstrapSnapshot(
            state=state,
            topology=topology,
            last_result=self._last_result,
            last_updated_at=datetime.now(tz=timezone.utc),
        )


# A streaming/IO import placeholder; keep typing.IO referenced for
# downstream consumers (e.g. custom exposure strategies) without
# affecting runtime.
_ = (Mapping, IO)
