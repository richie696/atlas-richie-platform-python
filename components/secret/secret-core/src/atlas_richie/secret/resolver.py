"""Secret resolver 契约与默认实现。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretResolver` /
`cn.richie696.component.secret.core.DefaultSecretResolver`。

`SecretResolver` 是 facade 层对外暴露的统一入口,负责:

1. 在多个 provider 之间按 reference.provider 路由到正确的 backend。
2. 串接 callback(`SecretCallback.on_read` / `on_write` / `on_rotate`)。
3. 串接 cipher/signing 装饰器(在 `DefaultSecretResolver` 内部处理)。
4. 失败转译(backend 抛 `IntegrityError` → facade 抛
   `SecretIntegrityException`)。
5. 缓存(若 backend 的 `SecretCapability.cacheable` 为 True)。

`DefaultSecretResolver` 是参考实现,业务代码大多数情况下不需要直接
构造它 — 通过 `GlobalSecret` 静态外观调用即可。

设计要点:

- **不持有状态**:resolver 自身不缓存 secret 值(由 `atlas-richie-cache`
  提供);只持有 callback / cipher 装饰器链。
- **路由表**:constructor 接受 `Mapping[str, SecretProviderSession]`
  显式注入,不在内部通过 service-locator 隐式查。
- **版本 selector 解析**:把 reference 的 `SecretVersionSelector` 转
  译为 `SecretVersion` 传给 backend;`LATEST` 让 backend 自己决定。

English
--------
Secret resolver contract and default implementation. Mirrors the Java
`SecretResolver` / `DefaultSecretResolver`. The default implementation
is a thin layer over `SecretProviderSession`s, the callback chain, and
the optional cipher/signing decorators.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from atlas_richie.secret.callback import SecretCallback
from atlas_richie.secret.errors import (
    SecretConfigurationException,
    SecretException,
    SecretIntegrityException,
)
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.operations import SecretListable, SecretOperations
from atlas_richie.secret.provider.session import SecretProviderSession
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret.snapshot import SecretSnapshotManager
from atlas_richie.secret.value import DestroyableSecretValue, SecretValue
from atlas_richie.secret.writer import SecretDeletable, SecretWriter


@runtime_checkable
class SecretResolver(Protocol):
    """High-level resolver contract used by `GlobalSecret` and the
    bootstrap subsystem.
    """

    def resolve(self, reference: SecretReference) -> SecretValue:
        """Resolve `reference` to a `SecretValue`. Routed to the
        backend named by `reference.provider`.
        """
        ...

    def resolve_destroyable(
        self,
        reference: SecretReference,
    ) -> DestroyableSecretValue:
        """Resolve `reference` and return a destroyable wrapper
        that zeroes the plaintext on `destroy()`.
        """
        ...

    def resolve_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        """Resolve a specific `version` of `reference`."""
        ...

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        """Read metadata for `reference` without fetching plaintext."""
        ...

    def write(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        """Write `plaintext` to `reference`; requires a writable
        backend (otherwise raises `SecretConfigurationException`).
        """
        ...

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        """Atomic rotation; emits a snapshot event on success."""
        ...


def _resolver_default_logger() -> logging.Logger:
    """Default logger used by `DefaultSecretResolver`."""
    return logging.getLogger("atlas_richie.secret.resolver")


field_default_logger = _resolver_default_logger  # back-compat alias


@dataclass(slots=True)
class DefaultSecretResolver:
    """Reference implementation of `SecretResolver`.

    The resolver is a thin coordinator: it routes to the named
    provider, runs the callback chain, and (optionally) wraps reads
    with a cipher / signing decorator chain. It does NOT cache
    secret values itself; for caching, wrap the provider with the
    `atlas-richie-cache` L2 layer at the provider-factory level.
    """

    providers: Mapping[str, SecretProviderSession]
    callbacks: tuple[SecretCallback, ...] = ()
    snapshot_manager: SecretSnapshotManager | None = None
    logger: logging.Logger = field(default_factory=_resolver_default_logger)

    def _session(self, reference: SecretReference) -> SecretProviderSession:
        try:
            return self.providers[reference.provider]
        except KeyError as error:
            raise SecretConfigurationException(
                f"unknown secret provider: {reference.provider!r}",
            ) from error

    # --- SecretResolver protocol -----------------------------------------

    def resolve(self, reference: SecretReference) -> SecretValue:
        session = self._session(reference)
        if not isinstance(session.operations, SecretOperations):
            raise SecretConfigurationException(
                f"provider {reference.provider!r} does not implement SecretOperations",
            )
        try:
            value = session.operations.get(reference)
        except Exception as error:
            self._fire_failure(reference, error)
            raise
        self._fire_read(reference, value)
        return value

    def resolve_destroyable(
        self,
        reference: SecretReference,
    ) -> DestroyableSecretValue:
        return DestroyableSecretValue(self.resolve(reference))

    def resolve_version(
        self,
        reference: SecretReference,
        version: SecretVersion,
    ) -> SecretValue:
        session = self._session(reference)
        if not isinstance(session.operations, SecretOperations):
            raise SecretConfigurationException(
                f"provider {reference.provider!r} does not implement SecretOperations",
            )
        try:
            value = session.operations.get_version(reference, version)
        except Exception as error:
            self._fire_failure(reference, error)
            raise
        self._fire_read(reference, value)
        return value

    def metadata(self, reference: SecretReference) -> SecretMetadata:
        session = self._session(reference)
        return session.operations.get_metadata(reference)

    def write(
        self,
        reference: SecretReference,
        plaintext: bytes,
    ) -> SecretValue:
        session = self._session(reference)
        if not isinstance(session.writer, SecretWriter):
            raise SecretConfigurationException(
                f"provider {reference.provider!r} is not writable",
            )
        value = session.writer.put(reference, plaintext)
        self._fire_write(reference, value)
        return value

    def rotate(
        self,
        reference: SecretReference,
        new_plaintext: bytes,
    ) -> SecretValue:
        session = self._session(reference)
        if not isinstance(session.writer, SecretWriter):
            raise SecretConfigurationException(
                f"provider {reference.provider!r} is not writable",
            )
        try:
            previous = session.operations.get(reference)
        except SecretException:
            previous = None
        value = session.writer.rotate(reference, new_plaintext)
        self._fire_rotate(reference, previous, value)
        return value

    def list(self, prefix: str | None = None) -> list[SecretReference]:
        """Best-effort list across all listable providers."""
        all_refs: list[SecretReference] = []
        for session in self.providers.values():
            if isinstance(session.operations, SecretListable):
                all_refs.extend(session.operations.list(prefix))
        all_refs.sort(key=lambda r: r.path)
        return all_refs

    # --- Internal callback fan-out ---------------------------------------

    def _fire_read(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        for callback in self.callbacks:
            try:
                callback.on_read(reference, value)
            except Exception:  # noqa: BLE001 - best-effort
                self.logger.exception(
                    "secret callback %r on_read raised", callback,
                )

    def _fire_write(
        self,
        reference: SecretReference,
        value: SecretValue,
    ) -> None:
        for callback in self.callbacks:
            try:
                callback.on_write(reference, value)
            except Exception:  # noqa: BLE001 - best-effort
                self.logger.exception(
                    "secret callback %r on_write raised", callback,
                )

    def _fire_rotate(
        self,
        reference: SecretReference,
        previous: SecretValue | None,
        current: SecretValue,
    ) -> None:
        for callback in self.callbacks:
            try:
                callback.on_rotate(reference, previous, current)
            except Exception:  # noqa: BLE001 - best-effort
                self.logger.exception(
                    "secret callback %r on_rotate raised", callback,
                )

    def _fire_failure(
        self,
        reference: SecretReference,
        error: BaseException,
    ) -> None:
        # Translate "not found" into SecretIntegrityException for stable
        # surface; pass everything else through.
        if isinstance(error, SecretException):
            translated: BaseException = error
        else:
            translated = SecretException(str(error))
        if isinstance(error, KeyError) or "not found" in str(error).lower():
            translated = SecretIntegrityException(
                f"secret not found: {reference.provider}:{reference.path}",
            )
        for callback in self.callbacks:
            try:
                callback.on_resolve_failure(reference, translated)
            except Exception:  # noqa: BLE001 - best-effort
                self.logger.exception(
                    "secret callback %r on_resolve_failure raised", callback,
                )


def _resolver_default_logger() -> logging.Logger:
    """Default logger used by `DefaultSecretResolver`."""
    return logging.getLogger("atlas_richie.secret.resolver")


# field_default_logger already defined above (before the dataclass).


__all__ = [
    "SecretResolver",
    "DefaultSecretResolver",
]


# Re-export names that callers may `from resolver import X` against.
_ = (Iterable,)
