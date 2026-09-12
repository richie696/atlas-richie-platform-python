"""Install every built distribution in a fresh virtual environment.

Run after ``prepare_wheelhouse.py``.  Atlas Richie wheels and their locked
third-party runtime dependencies are resolved only from local build artifacts, so
this check cannot accidentally use the editable workspace environment or an index.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


def _read_platform_version() -> str:
    """Read the canonical version from the repo-root ``versions.toml``.

    The release script must agree with the rest of the toolchain about
    which wheel version is in flight, otherwise ``pip install`` would
    silently resolve the latest published (older) release and the check
    would pass against the wrong artifact.  Falls back to ``"0.0.0"`` if
    the file is unreadable so the test still reports a clear failure.
    """

    versions_path = Path(__file__).resolve().parents[2] / "versions.toml"
    try:
        text = versions_path.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r'^\s*platform-version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


_VERSION = _read_platform_version()

PACKAGES = (
    (f"atlas-richie-contracts=={_VERSION}", "atlas_richie.contracts"),
    (f"atlas-richie-testing=={_VERSION}", "atlas_richie.testing"),
    (f"atlas-richie-http=={_VERSION}", "atlas_richie.http"),
    (f"atlas-richie-mcp=={_VERSION}", "atlas_richie.mcp"),
    (f"atlas-richie-resilience=={_VERSION}", "atlas_richie.resilience"),
    (f"atlas-richie-cache-core=={_VERSION}", "atlas_richie.cache_core"),
    (f"atlas-richie-cache-redis=={_VERSION}", "atlas_richie.cache_redis"),
    (f"atlas-richie-secret-core=={_VERSION}", "atlas_richie.secret"),
    (f"atlas-richie-secret-redis=={_VERSION}", "atlas_richie.secret_redis"),
    (f"atlas-richie-oauth=={_VERSION}", "atlas_richie.oauth"),
    (f"atlas-richie-platform=={_VERSION}", "atlas_richie.platform"),
)


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    wheelhouse = repository / "dist"
    dependency_wheelhouse = wheelhouse / "wheelhouse"
    for package, module in PACKAGES:
        with tempfile.TemporaryDirectory(prefix="atlas-richie-wheel-") as temporary:
            environment = Path(temporary) / "venv"
            run(sys.executable, "-m", "venv", str(environment))
            python = environment / "bin" / "python"
            run(
                str(python),
                "-m",
                "pip",
                "install",
                "--no-cache-dir",
                "--no-index",
                "--find-links",
                str(wheelhouse),
                "--find-links",
                str(dependency_wheelhouse),
                package,
            )
            run(str(python), "-m", "pip", "check")
            run(str(python), "-c", f"import {module}; print({module}.__name__)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
