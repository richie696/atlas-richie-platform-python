"""Compare-and-swap byte records on a deployment-owned local POSIX mount."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
import fcntl
import os
import stat
import tempfile
from pathlib import Path
from typing import AsyncIterator, Iterator


class LocalAtomicFileStoreError(RuntimeError):
    """The local file authority is unavailable or violates its safety contract."""


class LocalAtomicFileConflict(LocalAtomicFileStoreError):
    """The expected record was changed by another writer."""


class LocalAtomicFileStore:
    """Read and byte-CAS one private file using a sidecar advisory lock.

    This component promises local POSIX semantics only. Deployments must verify
    atomic rename and advisory lock behavior before using a shared mount.
    """

    def __init__(self, path: Path, *, maximum_bytes: int = 16_384) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("atomic file path must be absolute")
        if type(maximum_bytes) is not int or maximum_bytes < 1:
            raise ValueError("atomic file size limit must be positive")
        self._path = path
        self._lock_path = path.with_name(f".{path.name}.lock")
        self._maximum_bytes = maximum_bytes

    async def read(self) -> bytes | None:
        """Read one complete record, or return None only when the file is absent."""
        return await asyncio.to_thread(self._read_sync)

    async def compare_and_swap(
        self, expected: bytes | None, replacement: bytes
    ) -> None:
        """Atomically replace only the exact previously-read byte record."""
        if expected is not None and not isinstance(expected, bytes):
            raise TypeError("expected atomic file content must be bytes or None")
        if not isinstance(replacement, bytes) or len(replacement) > self._maximum_bytes:
            raise ValueError("replacement atomic file content is invalid")
        await asyncio.to_thread(self._compare_and_swap_sync, expected, replacement)

    @asynccontextmanager
    async def hold_exclusive_lock(self) -> AsyncIterator[None]:
        """Hold this store's advisory lock across an async workflow.

        Use a dedicated lock-store path when the protected workflow also reads
        or writes another LocalAtomicFileStore; re-entering the same flock from
        a separate file descriptor would block.
        """
        acquisition = asyncio.create_task(
            asyncio.to_thread(self._open_locked_descriptor)
        )
        try:
            descriptor = await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            # A cancelled await does not stop the worker thread. Reap and close
            # a descriptor it may still acquire, or the deployment lock leaks.
            descriptor = await acquisition
            await asyncio.shield(asyncio.to_thread(os.close, descriptor))
            raise
        try:
            yield
        finally:
            await asyncio.shield(asyncio.to_thread(os.close, descriptor))

    def _read_sync(self) -> bytes | None:
        with self._exclusive_lock():
            self._verify_parent()
            try:
                return self._read_unlocked()
            except FileNotFoundError:
                return None

    def _compare_and_swap_sync(
        self, expected: bytes | None, replacement: bytes
    ) -> None:
        with self._exclusive_lock():
            self._verify_parent()
            try:
                current = self._read_unlocked()
            except FileNotFoundError:
                current = None
            if current != expected:
                raise LocalAtomicFileConflict(
                    "atomic file record changed concurrently"
                )
            self._replace_unlocked(replacement)

    def _verify_parent(self) -> None:
        current = Path(self._path.anchor)
        for component in self._path.parent.parts[1:]:
            current /= component
            try:
                mode = current.lstat().st_mode
            except OSError:
                raise LocalAtomicFileStoreError(
                    "atomic file parent directory is unavailable"
                ) from None
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise LocalAtomicFileStoreError(
                    "atomic file parent directory is unsafe"
                )
        if not os.access(self._path.parent, os.W_OK | os.X_OK):
            raise LocalAtomicFileStoreError(
                "atomic file parent directory is not writable"
            )

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        descriptor = self._open_locked_descriptor()
        try:
            yield
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _open_locked_descriptor(self) -> int:
        self._verify_parent()
        if not hasattr(os, "O_NOFOLLOW"):
            raise LocalAtomicFileStoreError("atomic file requires no-follow support")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self._lock_path,
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600,
            )
            lock_stat = os.fstat(descriptor)
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or stat.S_IMODE(lock_stat.st_mode) & 0o077
            ):
                raise LocalAtomicFileStoreError("atomic file lock is unsafe")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except LocalAtomicFileStoreError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            raise LocalAtomicFileStoreError("atomic file lock is unavailable") from None
        return descriptor

    def _read_unlocked(self) -> bytes:
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                record_stat = os.fstat(stream.fileno())
                if (
                    not stat.S_ISREG(record_stat.st_mode)
                    or stat.S_IMODE(record_stat.st_mode) & 0o077
                    or record_stat.st_size > self._maximum_bytes
                ):
                    raise LocalAtomicFileStoreError("atomic file record is unsafe")
                content = stream.read(self._maximum_bytes + 1)
        except FileNotFoundError:
            raise
        except LocalAtomicFileStoreError:
            raise
        except OSError:
            raise LocalAtomicFileStoreError(
                "atomic file record is unavailable"
            ) from None
        if len(content) > self._maximum_bytes:
            raise LocalAtomicFileStoreError("atomic file record exceeds its size limit")
        return content

    def _replace_unlocked(self, replacement: bytes) -> None:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self._path.name}.", dir=self._path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(replacement)
                stream.flush()
                os.fsync(descriptor)
            os.replace(temporary_path, self._path)
            parent_descriptor = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        except OSError:
            raise LocalAtomicFileStoreError(
                "atomic file record could not be persisted"
            ) from None
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
