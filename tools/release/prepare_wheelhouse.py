"""Materialize hash-verified runtime wheels for offline installation checks.

Some locked dependencies publish only source distributions. pip verifies their
locked source hashes and builds wheels in isolation during this online preparation
step; the subsequent installation check remains strictly offline. Build-system
dependencies follow each upstream sdist's build requirements, not the runtime lock.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, check=True, cwd=cwd)


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, default=repository / "dist")
    arguments = parser.parse_args()
    wheelhouse = arguments.wheel_dir.resolve() / "wheelhouse"
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
            cwd=repository,
        )
        # uv workspace environments deliberately need not contain pip. Keep the
        # downloader in a disposable stdlib venv, outside the editable workspace.
        downloader = Path(temporary) / "downloader"
        run(sys.executable, "-m", "venv", str(downloader), cwd=repository)
        run(
            str(downloader / "bin" / "python"),
            "-I",
            "-m",
            "pip",
            "--isolated",
            "wheel",
            "--no-cache-dir",
            "--require-hashes",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            "--requirement",
            str(requirements),
            cwd=repository,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
