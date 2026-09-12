"""`SecretRotationDaemon` — 后台轮询 secret metadata + 调度 rotation callbacks。

中文
----
对位 Java `cn.richie696.component.secret.bootstrap.RotationPublisher`
(Java 端在每个 `AbstractRemoteProviderFactory` 内部自带,Python 端
抽到独立 wheel 给所有 backend 共用)。

设计:

- **每条 reference 独立追踪 last-seen version**:`dict[id(reference)] -> version`
- **polling 线程**:`threading.Thread(daemon=True)`,定时拉取
  `operations.get_metadata(reference)`,跟 last-seen 对比
- **同步 callback**:`SecretRotationCallback` 在 polling 线程
  上同步触发,consumer 在 callback 里直接 `get(reference)` 重新
  拿 value(consumer 自己负责同步原语)
- **生命周期**:`start()` 启动线程,`stop()` 设 flag 优雅退出,
  重复 start/stop 是幂等的
- **错误隔离**:单条 reference 的 metadata 拉取失败不影响其它
  reference(用 `try/except` 包住,失败只 log warning)

英文
--------
Background daemon that watches `SecretOperations.get_metadata`
for version changes. Mirrors Java's `RotationPublisher` hook
(generalized to all backends, not just remote ones).

Design:

- Per-reference last-seen version (`dict[id(reference)] -> version`)
- Polling thread: `threading.Thread(daemon=True)`; on each tick,
  call `operations.get_metadata(reference)` and compare.
- Synchronous callback: invoked on the polling thread. Consumers
  re-resolve by calling `session.get(reference)` themselves.
- Lifecycle: `start()` / `stop()`; both are idempotent.
- Error isolation: per-reference try/except; failures do not
  affect other references.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import NamedTuple

from atlas_richie.secret.errors import SecretException
from atlas_richie.secret.metadata import SecretMetadata
from atlas_richie.secret.operations import SecretOperations
from atlas_richie.secret.reference import SecretReference, SecretVersion
from atlas_richie.secret_rotation_daemon.events import (
    SecretRotated,
    SecretRotationCallback,
)

_logger = logging.getLogger("atlas_richie.secret_rotation_daemon")


class _Registration(NamedTuple):
    """One watch entry: the `SecretReference` + the callback to
    invoke when the version changes. The list of registrations
    is shared between the caller thread (register / unregister)
    and the polling thread; the daemon's lock guards mutations.
    """
    reference: SecretReference
    callback: SecretRotationCallback


class SecretRotationDaemon:
    """Background daemon that polls for secret version changes.

    Constructor parameters:

    - `operations`: any `SecretOperations` provider (typically
      `session.operations` for a live `SecretProviderSession`).
    - `poll_interval_seconds`: how often to call
      `get_metadata` for each registered reference. Default
      30s; reduce for faster rotation detection at the cost
      of more API calls.
    - `time_source`: injectable `Callable[[], float]` for
      deterministic tests. Default `time.monotonic`.

    Lifecycle:

    - `register(reference, callback)` — start watching
      `reference`. The callback is invoked on the polling
      thread when the version changes.
    - `start()` / `stop()` — start/stop the polling thread.
      Both are idempotent; calling `start()` twice is a no-op.
    - `unregister(reference)` — stop watching.
    - `close()` — convenience: `stop()` + `unregister()` all.

    Thread safety:

    - `register` / `unregister` lock a mutex; they may be called
      concurrently with the polling thread.
    - Callbacks run on the polling thread, **not** the caller's
      thread. The callback may block briefly but should not run
      for seconds (it holds the daemon's polling tick).
    """

    __slots__ = (
        "_closed",
        "_lock",
        "_operations",
        "_poll_interval_seconds",
        "_registrations",
        "_running",
        "_stop_event",
        "_thread",
        "_time_source",
        "_versions",
    )

    def __init__(
        self,
        operations: SecretOperations,
        *,
        poll_interval_seconds: float = 30.0,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be > 0")
        self._operations = operations
        self._poll_interval_seconds = poll_interval_seconds
        self._time_source = time_source or time.monotonic
        self._registrations: dict[int, _Registration] = {}
        self._versions: dict[int, SecretVersion] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed = False

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def registered_count(self) -> int:
        with self._lock:
            return len(self._registrations)

    def register(
        self,
        reference: SecretReference,
        callback: SecretRotationCallback,
    ) -> None:
        """Start watching `reference`. `callback` is invoked on
        the polling thread when the version changes.
        """
        if self._closed:
            raise SecretException(
                "secret_rotation_daemon: cannot register on a closed daemon",
            )
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            self._registrations[id(reference)] = _Registration(
                reference=reference, callback=callback,
            )
            # Force the next poll to treat this reference as
            # "new": do not pre-seed the last-seen version so
            # the first poll may fire (if the backend reports
            # a version we haven't seen yet). This makes the
            # daemon's behavior predictable on cold start.
            self._versions.pop(id(reference), None)
        _logger.debug("registered rotation watcher for %r", reference.path)

    def unregister(self, reference: SecretReference) -> None:
        with self._lock:
            self._registrations.pop(id(reference), None)
            self._versions.pop(id(reference), None)
        _logger.debug("unregistered rotation watcher for %r", reference.path)

    def start(self) -> None:
        """Start the polling thread. Idempotent."""
        if self._closed:
            raise SecretException(
                "secret_rotation_daemon: cannot start a closed daemon",
            )
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="secret-rotation-daemon",
                daemon=True,
            )
            self._running = True
            self._thread.start()
        _logger.debug("rotation daemon started")

    def stop(self) -> None:
        """Stop the polling thread. Idempotent; blocks until the
        thread exits.
        """
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            thread = self._thread
        assert thread is not None
        thread.join(timeout=self._poll_interval_seconds * 2 + 5.0)
        with self._lock:
            self._running = False
            self._thread = None
        _logger.debug("rotation daemon stopped")

    def close(self) -> None:
        self.stop()
        with self._lock:
            self._closed = True
            self._registrations.clear()
            self._versions.clear()

    def poll_once(self) -> None:
        """Run a single poll tick synchronously. Useful for tests
        and for callers that want to drive the daemon manually
        (without starting a thread).
        """
        with self._lock:
            registrations = list(self._registrations.values())
        if not registrations:
            return
        for reg in registrations:
            try:
                metadata = self._operations.get_metadata(reg.reference)
            except SecretException as error:
                _logger.warning(
                    "rotation daemon: get_metadata(%r) failed: %s; "
                    "skipping this tick",
                    reg.reference.path,
                    error,
                )
                continue
            self._maybe_invoke(reg.reference, metadata, reg.callback)

    # --- Internal: the polling loop -------------------------------------

    def _run_loop(self) -> None:
        """Daemon's polling thread body.

        The thread sleeps between polls using `Event.wait(...)`
        so `stop()` can interrupt the sleep quickly.
        """
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001
                # Defensive: a bug in the daemon's own code must
                # not kill the polling thread silently.
                _logger.exception("secret_rotation_daemon: poll tick crashed")
            # Sleep with interrupt support.
            self._stop_event.wait(timeout=self._poll_interval_seconds)

    def _maybe_invoke(
        self,
        reference: SecretReference,
        metadata: SecretMetadata,
        callback: SecretRotationCallback,
    ) -> None:
        """Compare the just-fetched `metadata` against the
        last-seen version, and invoke the callback if the
        version changed.

        The comparison is on `SecretVersion.number` (the
        backend-assigned version id / sequence), not the full
        `SecretVersion` object — backends return a fresh
        `created_at` timestamp on every read, so equality of the
        full `SecretVersion` would always be False and fire on
        every poll.
        """
        ref_id = id(reference)
        new_version = metadata.version
        with self._lock:
            last_seen = self._versions.get(ref_id)
            if last_seen is not None and last_seen.number == new_version.number:
                # No change.
                return
            self._versions[ref_id] = new_version
            old_version = last_seen
        event = SecretRotated(
            reference=reference,
            old_version=old_version,
            new_version=new_version,
        )
        try:
            callback(event)
        except Exception:  # noqa: BLE001
            # Per-callback error isolation: one bad consumer
            # must not kill the daemon or block other consumers.
            _logger.exception(
                "rotation daemon: callback for %r raised; continuing",
                reference.path,
            )


__all__ = ["SecretRotationDaemon"]
