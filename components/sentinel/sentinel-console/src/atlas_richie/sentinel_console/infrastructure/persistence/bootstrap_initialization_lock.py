"""Local POSIX adapter for serializing first-run setup side effects."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from pathlib import Path

from ...application.bootstrap_ports import BootstrapInitializationLock
from .local_atomic_file_store import LocalAtomicFileStore


class LocalBootstrapInitializationLock(BootstrapInitializationLock):
    """Hold a dedicated advisory lock for the duration of setup orchestration.

    All Console workers for one installation must use the same lock path on a
    local POSIX filesystem. The path must be distinct from data-store paths so
    setup can read/write those stores while this lock is held.
    """

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("bootstrap initialization lock path must be absolute")
        self._store = LocalAtomicFileStore(path, maximum_bytes=1)

    def acquire(self) -> AbstractAsyncContextManager[None]:
        """Return the cross-worker file-lock context manager."""
        return self._store.hold_exclusive_lock()


__all__ = ["LocalBootstrapInitializationLock"]
