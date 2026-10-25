"""Focused tests for deployment-owned setup-window state and local file CAS."""

from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
from pathlib import Path

import pytest

from atlas_richie.sentinel_console.application.errors import (
    BootstrapAuthorityUnavailable,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    local_atomic_file_store as atomic_file_store,
)
from atlas_richie.sentinel_console.infrastructure.persistence import (
    setup_window_file_store as setup_store,
)


def _attempt_setup_window_write(
    path: str,
    expected_revision: str,
    is_open: bool,
    gate: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    """Independent worker process competing on the same local setup-window record."""
    store = setup_store.SetupWindowFileStore(Path(path))
    if not gate.wait(timeout=10):
        results.put("gate-timeout")
        return
    try:
        revision = asyncio.run(
            store.set_setup_window_open(
                is_open, expected_revision=expected_revision
            )
        )
    except setup_store.SetupWindowRevisionConflict:
        results.put("conflict")
    else:
        results.put(("updated", is_open, revision))


def test_missing_window_is_closed_and_state_can_be_opened_then_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "setup-window.json"
    store = setup_store.SetupWindowFileStore(path)

    async def scenario() -> None:
        assert await store.is_setup_window_open() is False
        open_revision = await store.set_setup_window_open(
            True, expected_revision=None
        )
        assert await store.is_setup_window_open() is True
        close_revision = await store.set_setup_window_open(
            False, expected_revision=open_revision
        )
        assert close_revision != open_revision
        assert await store.is_setup_window_open() is False

    asyncio.run(scenario())
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.with_name(".setup-window.json.lock").stat().st_mode & 0o777 == 0o600


def test_stale_revision_and_concurrent_updates_conflict(tmp_path: Path) -> None:
    store = setup_store.SetupWindowFileStore(tmp_path / "setup-window.json")

    async def scenario() -> None:
        revision = await store.set_setup_window_open(True, expected_revision=None)
        outcomes = await asyncio.gather(
            store.set_setup_window_open(False, expected_revision=revision),
            store.set_setup_window_open(True, expected_revision=revision),
            return_exceptions=True,
        )
        assert sum(isinstance(item, str) for item in outcomes) == 1
        assert sum(
            isinstance(item, setup_store.SetupWindowRevisionConflict)
            for item in outcomes
        )
        with pytest.raises(setup_store.SetupWindowRevisionConflict):
            await store.set_setup_window_open(False, expected_revision=revision)

    asyncio.run(scenario())


def test_independent_worker_processes_compare_and_swap_one_setup_window(
    tmp_path: Path,
) -> None:
    path = tmp_path / "setup-window.json"
    store = setup_store.SetupWindowFileStore(path)
    open_revision = asyncio.run(
        store.set_setup_window_open(True, expected_revision=None)
    )
    context = multiprocessing.get_context("spawn")
    gate = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_attempt_setup_window_write,
            args=(str(path), open_revision, is_open, gate, results),
        )
        for is_open in (False, True)
    ]
    try:
        for worker in workers:
            worker.start()
        gate.set()
        outcomes = [results.get(timeout=15) for _worker in workers]
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0

        assert sum(isinstance(outcome, tuple) for outcome in outcomes) == 1
        assert outcomes.count("conflict") == 1
        snapshot = asyncio.run(store.read_snapshot())
        winner = next(outcome for outcome in outcomes if isinstance(outcome, tuple))
        assert snapshot.is_open is winner[1]
        assert snapshot.revision == winner[2]
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        results.close()
        results.join_thread()


def test_concurrent_idempotent_close_leaves_setup_window_closed(
    tmp_path: Path,
) -> None:
    store = setup_store.SetupWindowFileStore(tmp_path / "setup-window.json")

    async def scenario() -> None:
        await store.set_setup_window_open(True, expected_revision=None)
        await asyncio.gather(
            *(store.close_setup_window_if_open() for _ in range(8))
        )
        assert await store.is_setup_window_open() is False

    asyncio.run(scenario())


def test_cancelling_lock_holder_releases_the_deployment_lock(
    tmp_path: Path,
) -> None:
    lock_store = setup_store.LocalAtomicFileStore(
        tmp_path / "bootstrap-lock", maximum_bytes=1
    )

    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_then_wait() -> None:
            async with lock_store.hold_exclusive_lock():
                entered.set()
                await release.wait()

        holder = asyncio.create_task(hold_then_wait())
        await entered.wait()
        holder.cancel()
        with pytest.raises(asyncio.CancelledError):
            await holder

        async with asyncio.timeout(1):
            async with lock_store.hold_exclusive_lock():
                pass

    asyncio.run(scenario())


def test_lock_context_explicitly_unlocks_before_closing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations: list[int] = []
    original_flock = atomic_file_store.fcntl.flock

    def track_flock(descriptor: int, operation: int) -> None:
        operations.append(operation)
        original_flock(descriptor, operation)

    monkeypatch.setattr(atomic_file_store.fcntl, "flock", track_flock)
    lock_store = atomic_file_store.LocalAtomicFileStore(
        tmp_path / "bootstrap-lock", maximum_bytes=1
    )

    async def scenario() -> None:
        async with lock_store.hold_exclusive_lock():
            pass

    asyncio.run(scenario())
    assert operations == [
        atomic_file_store.fcntl.LOCK_EX | atomic_file_store.fcntl.LOCK_NB,
        atomic_file_store.fcntl.LOCK_UN,
    ]


def test_lock_context_retries_nonblocking_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    original_flock = atomic_file_store.fcntl.flock

    def contend_then_acquire(descriptor: int, operation: int) -> None:
        nonlocal attempts
        exclusive_nonblocking = (
            atomic_file_store.fcntl.LOCK_EX | atomic_file_store.fcntl.LOCK_NB
        )
        if operation == exclusive_nonblocking:
            attempts += 1
            if attempts < 3:
                raise BlockingIOError(errno.EAGAIN, "lock is busy")
        original_flock(descriptor, operation)

    monkeypatch.setattr(atomic_file_store.fcntl, "flock", contend_then_acquire)
    lock_store = atomic_file_store.LocalAtomicFileStore(
        tmp_path / "bootstrap-lock", maximum_bytes=1
    )

    async def scenario() -> None:
        async with lock_store.hold_exclusive_lock():
            pass

    asyncio.run(scenario())
    assert attempts == 3


@pytest.mark.parametrize(
    "payload",
    (
        b"\xff",
        b"{",
        b'{"schema_version":1,"is_open":true,"revision":"bad"}',
        (
            b'{"schema_version":1,"is_open":true,"revision":"'
            b'00000000-0000-4000-8000-000000000000","extra":false}'
        ),
        (
            b'{"schema_version":true,"is_open":true,"revision":"'
            b'00000000-0000-4000-8000-000000000000"}'
        ),
        (
            b'{"schema_version":2,"is_open":true,"revision":"'
            b'00000000-0000-4000-8000-000000000000"}'
        ),
        (
            b'{"schema_version":1,"is_open":true,"is_open":false,"revision":"'
            b'00000000-0000-4000-8000-000000000000"}'
        ),
    ),
)
def test_corrupt_or_ambiguous_state_fails_closed(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "setup-window.json"
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    store = setup_store.SetupWindowFileStore(path)

    with pytest.raises(BootstrapAuthorityUnavailable):
        asyncio.run(store.is_setup_window_open())


def test_permissive_mode_and_symlink_are_unavailable_not_open(tmp_path: Path) -> None:
    path = tmp_path / "setup-window.json"
    store = setup_store.SetupWindowFileStore(path)
    asyncio.run(store.set_setup_window_open(True, expected_revision=None))
    os.chmod(path, 0o644)
    with pytest.raises(BootstrapAuthorityUnavailable):
        asyncio.run(store.is_setup_window_open())

    path.unlink()
    path.symlink_to(tmp_path / "other.json")
    with pytest.raises(BootstrapAuthorityUnavailable):
        asyncio.run(store.is_setup_window_open())
