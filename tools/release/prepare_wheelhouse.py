"""Materialize locked third-party runtime wheels for offline installation checks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    wheelhouse = repository / "dist" / "wheelhouse"
    wheelhouse.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atlas-richie-lock-") as temporary:
        requirements = Path(temporary) / "runtime-requirements.txt"
        run(
            "uv",
            "export",
            "--all-packages",
            "--no-emit-local",
            "--no-dev",
            "--format",
            "requirements.txt",
            "--output-file",
            str(requirements),
            "--locked",
        )
        run(
            sys.executable,
            "-m",
            "pip",
            "download",
            "--no-cache-dir",
            "--require-hashes",
            "--only-binary=:all:",
            "--dest",
            str(wheelhouse),
            "--requirement",
            str(requirements),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
