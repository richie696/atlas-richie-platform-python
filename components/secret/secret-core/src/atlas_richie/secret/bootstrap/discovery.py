"""Secret 启动期 provider 发现。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.SecretProviderDiscovery`。

`SecretProviderDiscovery` — 在 bootstrap 之前 / 之中扫描已注册的
`SecretProviderFactory`,构建 `SecretProviderTopology`:

- 哪些 provider 已注册?
- 每个 provider 服务的 binding 数?
- 是否存在"binding 引用了未注册 provider"的孤儿?

发现策略:

- **静态发现**(`discover_static`):仅看 `SecretRegistry`,不实际
  open session;零 IO,可在 bootstrap 之前做 sanity check。
- **可达性发现**(`discover_reachable`):open 每个 session,失败
  的标记 `unreachable` 但不中断;适合 debug 阶段。
- **强制 readiness**(`require_all_reachable`):任何 unreachable 抛
  `SecretBootstrapException`,适合生产。

返回 `SecretProviderTopology` + 可选 `unreachable` provider 集合。

English
--------
Secret bootstrap provider discovery. Mirrors the Java
`SecretProviderDiscovery`. `discover_static` is zero-IO and
suitable for pre-bootstrap sanity checks; `discover_reachable`
opens every session to surface connection issues; the strict
variant raises on any unreachable provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from atlas_richie.secret.bootstrap.state import SecretProviderTopology
from atlas_richie.secret.errors import SecretBootstrapException
from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.registry.secret_registry import SecretRegistry


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Outcome of a discovery pass.

    Attributes:
        topology: Provider topology with backend / binding-count
            information.
        unreachable: Provider names that could not be opened
            (only populated by `discover_reachable` and
            `require_all_reachable`).
    """

    topology: SecretProviderTopology
    unreachable: tuple[str, ...] = ()


class SecretProviderDiscovery:
    """Bootstrap-time provider discovery + reachability probe."""

    def __init__(self, registry: SecretRegistry) -> None:
        self._registry = registry

    def discover_static(self) -> DiscoveryResult:
        """Inspect the registry without opening sessions.

        Counts bindings per provider by scanning every binding in
        every catalog registered with the registry.
        """
        provider_backends: dict[str, SecretBackend] = {}
        binding_counts: dict[str, int] = {}
        for name, session in self._registry.sessions().items():
            provider_backends[name] = session.descriptor.backend
            binding_counts[name] = 0
        for catalog in self._registry.catalogs():
            for binding in catalog.bindings:
                binding_counts[binding.reference.provider] = (
                    binding_counts.get(binding.reference.provider, 0) + 1
                )
        # Surface orphan bindings: a binding whose provider is
        # unknown to the registry is collected under "<orphan>".
        for name, count in binding_counts.items():
            if name not in provider_backends:
                binding_counts["<orphan>"] = (
                    binding_counts.get("<orphan>", 0) + count
                )
        return DiscoveryResult(
            topology=SecretProviderTopology(
                providers=provider_backends,
                binding_counts=binding_counts,
            ),
        )

    def discover_reachable(self) -> DiscoveryResult:
        """Open every session and report the unreachable ones."""
        sessions: list[tuple[str, SecretProviderSession | Exception]] = []
        for name in self._registry.sessions():
            try:
                sessions.append((name, self._registry.session(name)))
            except Exception as error:  # noqa: BLE001
                sessions.append((name, error))
        unreachable: list[str] = []
        for name, value in sessions:
            if isinstance(value, Exception):
                unreachable.append(name)
        static = self.discover_static()
        return DiscoveryResult(
            topology=static.topology,
            unreachable=tuple(unreachable),
        )

    def require_all_reachable(self) -> DiscoveryResult:
        """Like `discover_reachable`, but raise on any unreachable."""
        result = self.discover_reachable()
        if result.unreachable:
            raise SecretBootstrapException(
                "unreachable providers during discovery: "
                + ", ".join(result.unreachable),
            )
        return result


__all__ = [
    "SecretProviderDiscovery",
    "DiscoveryResult",
]


_ = (Mapping, field)
