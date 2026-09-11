"""Install every built distribution in a fresh virtual environment.

Run after ``prepare_wheelhouse.py``.  Atlas Richie wheels and their locked
third-party runtime dependencies are resolved only from local build artifacts, so
this check cannot accidentally use the editable workspace environment or an index.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


PACKAGES = (
    ("atlas-richie-contracts==0.1.0", "atlas_richie.contracts"),
    ("atlas-richie-testing==0.1.0", "atlas_richie.testing"),
    ("atlas-richie-http==0.1.0", "atlas_richie.http"),
    ("atlas-richie-mcp==0.1.0", "atlas_richie.mcp"),
    ("atlas-richie-resilience==0.1.0", "atlas_richie.resilience"),
    ("atlas-richie-cache-core==0.1.0", "atlas_richie.cache_core"),
    ("atlas-richie-cache-redis==0.1.0", "atlas_richie.cache_redis"),
    ("atlas-richie-mcp-asgi==0.1.0", "atlas_richie.mcp_asgi"),
    ("atlas-richie-mcp-http==0.1.0", "atlas_richie.mcp_http"),
    ("atlas-richie-mcp-oauth==0.1.0", "atlas_richie.mcp_oauth"),
    ("atlas-richie-mcp-schema-jsonschema==0.1.0", "atlas_richie.mcp_schema_jsonschema"),
    ("atlas-richie-oauth==0.1.0", "atlas_richie.oauth"),
    ("atlas-richie-oauth-jose==0.1.0", "atlas_richie.oauth_jose"),
    ("atlas-richie-platform==0.1.0", "atlas_richie.platform"),
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
