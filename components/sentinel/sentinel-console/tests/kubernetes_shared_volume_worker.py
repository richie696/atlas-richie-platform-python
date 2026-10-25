"""Exercise the production file authority store from separate Kubernetes Pods."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time

from local_atomic_file_store import LocalAtomicFileConflict, LocalAtomicFileStore


class SharedVolumeWorker:
    """Run one competing CAS or verify persisted results on the mounted PVC."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._store = LocalAtomicFileStore(root / "authority.json")

    async def run_worker(self, index: int) -> None:
        if index == 0:
            await self._hold_lock_until_contender_is_ready()
        else:
            await self._wait_for(self._root / "lock-held")
            self._write_once(self._root / "contender-attempting", b"ready")

        started = time.monotonic()
        outcome = "stored"
        try:
            await self._store.compare_and_swap(None, f"pod-{index}".encode())
        except LocalAtomicFileConflict:
            outcome = "conflict"

        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._write_once(
            self._root / f"result-{index}.json",
            json.dumps(
                {"index": index, "outcome": outcome, "elapsed_ms": elapsed_ms},
                sort_keys=True,
            ).encode(),
        )

    async def verify(self) -> None:
        await self._wait_for(self._root / "result-0.json")
        await self._wait_for(self._root / "result-1.json")
        results = [
            json.loads((self._root / f"result-{index}.json").read_text())
            for index in range(2)
        ]
        outcomes = sorted(result["outcome"] for result in results)
        if outcomes != ["conflict", "stored"]:
            raise AssertionError(f"unexpected shared-volume CAS outcomes: {outcomes}")

        contender = next(result for result in results if result["index"] == 1)
        if contender["elapsed_ms"] < 500:
            raise AssertionError(
                "the second Pod did not wait on the cross-Pod advisory lock"
            )

        persisted = await self._store.read()
        if persisted not in {b"pod-0", b"pod-1"}:
            raise AssertionError(f"unexpected persisted authority value: {persisted!r}")
        print(
            json.dumps(
                {
                    "outcomes": outcomes,
                    "contender_wait_ms": contender["elapsed_ms"],
                    "persisted_winner": persisted.decode(),
                },
                sort_keys=True,
            )
        )

    async def _hold_lock_until_contender_is_ready(self) -> None:
        async with self._store.hold_exclusive_lock():
            self._write_once(self._root / "lock-held", b"held")
            await self._wait_for(self._root / "contender-attempting")
            await asyncio.sleep(1)

    async def _wait_for(self, path: Path) -> None:
        deadline = time.monotonic() + 45
        while not path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for {path.name}")
            await asyncio.sleep(0.02)

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)


def main() -> None:
    worker = SharedVolumeWorker(Path("/shared"))
    if sys.argv[1:] == ["verify"]:
        asyncio.run(worker.verify())
        return
    if sys.argv[1:] != ["worker"]:
        raise SystemExit("expected worker or verify")
    asyncio.run(worker.run_worker(int(os.environ["JOB_COMPLETION_INDEX"])))


if __name__ == "__main__":
    main()
