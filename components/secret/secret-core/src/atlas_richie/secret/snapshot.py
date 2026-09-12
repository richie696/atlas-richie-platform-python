"""Secret 快照管理:版本变更事件 + 监听器 + 运行期快照。

中文
----
对位 Java `cn.richie696.component.secret.api.SecretSnapshotChangedEvent` /
`SecretSnapshotListener` / `DefaultSecretOperations.SecretSnapshotManager` /
`SecretRuntimeSnapshot`。

- `SecretSnapshotChangedEvent` — frozen dataclass,描述一次"secret 状态
  变化"的事实(reference + 旧/新 metadata)。只携带元数据,不带明文。
- `SecretSnapshotListener` — Protocol,事件订阅方。Provider 在内部
  检测到轮转时构造 event 并通知所有 listener。
- `SecretSnapshotManager` — 维护 listener 列表;线程安全(用
  `threading.Lock`)。`register` / `unregister` / `publish` 三方法。
- `SecretRuntimeSnapshot` — 一次 resolve 时的运行时状态(包括当前已
  listen 的 listener 数量、上次 publish 时间等),用于诊断。

`SecretSnapshotManager` 在 SecretProvider 内部使用,facade 也可独立
实例化。`publish` 是 best-effort:listener 抛异常只 log,不影响后续
listener 与发布者。

English
--------
Secret snapshot manager. Mirrors the Java `SecretSnapshotChangedEvent`
/ `SecretSnapshotListener` / `SecretSnapshotManager` /
`SecretRuntimeSnapshot`. Listeners are notified on rotation; failures
in one listener do not block others.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.reference import SecretReference


@dataclass(frozen=True, slots=True)
class SecretSnapshotChangedEvent:
    """Immutable record of a secret state change.

    Attributes:
        reference: The secret whose state changed.
        previous_metadata: The metadata immediately before the change,
            or ``None`` if the secret was newly created.
        current_metadata: The metadata after the change.
        observed_at: UTC wall-clock time at which the manager
            observed the change.
    """

    reference: SecretReference
    previous_metadata: SecretMetadata | None
    current_metadata: SecretMetadata
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class SecretSnapshotListener(Protocol):
    """Observer that receives `SecretSnapshotChangedEvent`s."""

    def on_snapshot_changed(self, event: SecretSnapshotChangedEvent) -> None:
        """Handle a snapshot-change event. Best-effort: any exception
        is logged by the manager and the next listener is still
        invoked.
        """
        ...


@dataclass(frozen=True, slots=True)
class SecretRuntimeSnapshot:
    """Diagnostic snapshot of the secret subsystem at a moment in time.

    Attributes:
        active_provider: Name of the currently active provider, or
            ``None`` if no provider is installed.
        registered_listeners: Number of listeners currently registered
            on the snapshot manager.
        last_published_at: UTC time of the last snapshot event, or
            ``None`` if none has been published yet.
        total_published: Total number of events published since the
            manager was created.
    """

    active_provider: str | None
    registered_listeners: int
    last_published_at: datetime | None
    total_published: int


class SecretSnapshotManager:
    """Thread-safe listener registry + best-effort event publisher."""

    def __init__(self) -> None:
        self._listeners: list[SecretSnapshotListener] = []
        self._lock = threading.Lock()
        self._total_published: int = 0
        self._last_published_at: datetime | None = None

    def register(self, listener: SecretSnapshotListener) -> None:
        """Append a listener. Duplicate registrations are not
        deduplicated; the listener will receive each event twice if
        registered twice.
        """
        with self._lock:
            self._listeners.append(listener)

    def unregister(self, listener: SecretSnapshotListener) -> bool:
        """Remove the first matching listener. Returns ``True`` if
        any listener was removed.
        """
        with self._lock:
            for index, candidate in enumerate(self._listeners):
                if candidate is listener:
                    del self._listeners[index]
                    return True
            return False

    def clear(self) -> None:
        """Remove all listeners."""
        with self._lock:
            self._listeners.clear()

    def listeners(self) -> Iterable[SecretSnapshotListener]:
        """Snapshot of the currently registered listeners (read-only)."""
        with self._lock:
            return tuple(self._listeners)

    def publish(self, event: SecretSnapshotChangedEvent) -> None:
        """Notify all listeners of `event`. Listener exceptions are
        suppressed and logged via the Python `logging` framework; the
        publish itself never raises.

        Providers should call this from their rotation hook. Facade
        layer may also publish synthesized events (e.g. on bootstrap
        completion).
        """
        with self._lock:
            self._total_published += 1
            self._last_published_at = event.observed_at
            snapshot = tuple(self._listeners)
        for listener in snapshot:
            try:
                listener.on_snapshot_changed(event)
            except Exception as error:  # noqa: BLE001 - best-effort fan-out
                # Do not import logging lazily to keep import graph
                # minimal; stdlib logging is the standard sink.
                import logging

                logging.getLogger(__name__).exception(
                    "secret snapshot listener %r raised on event %r: %s",
                    listener,
                    event,
                    error,
                )

    def runtime_snapshot(self, *, active_provider: str | None) -> SecretRuntimeSnapshot:
        """Return a diagnostic view of the manager's state."""
        with self._lock:
            return SecretRuntimeSnapshot(
                active_provider=active_provider,
                registered_listeners=len(self._listeners),
                last_published_at=self._last_published_at,
                total_published=self._total_published,
            )

    @property
    def total_published(self) -> int:
        with self._lock:
            return self._total_published


__all__ = [
    "SecretSnapshotChangedEvent",
    "SecretSnapshotListener",
    "SecretRuntimeSnapshot",
    "SecretSnapshotManager",
]


# Avoid an unused-import lint complaint for SecretException (kept as a
# stable re-export anchor for callers that import this module to access
# the public surface).
_ = SecretException
