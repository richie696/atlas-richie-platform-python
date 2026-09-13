"""Cross-language contract test conftest.

Resolves paths to the Go CLI binary and the Java CLI jar, builds them on
demand if missing, and provides shared fixtures used by both
``test_go_mock.py`` and ``test_java_mock.py``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

CROSS_LANG_DIR = Path(__file__).parent
GO_DIR = CROSS_LANG_DIR / "go"
JAVA_DIR = CROSS_LANG_DIR / "java"
FIXTURES_DIR = CROSS_LANG_DIR / "fixtures"
GO_BINARY = Path("/tmp/atlas-richie-reporting-mock-go")
JAVA_JAR = JAVA_DIR / "target/reporting-mock.jar"


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


@pytest.fixture(scope="session")
def go_binary() -> Path:
    """Build the Go CLI binary if needed; yield its path."""
    if not _which("go"):
        pytest.skip("go executable not found on PATH")
    GO_BINARY.parent.mkdir(parents=True, exist_ok=True)
    if not GO_BINARY.exists() or os.stat(GO_BINARY).st_mtime < os.stat(GO_DIR / "encode.go").st_mtime:
        subprocess.run(
            ["go", "build", "-o", str(GO_BINARY), "."],
            cwd=str(GO_DIR),
            check=True,
        )
    return GO_BINARY


@pytest.fixture(scope="session")
def java_jar() -> Path:
    """Build the Java CLI jar if needed; yield its path."""
    if not _which("mvn"):
        pytest.skip("mvn (Maven) not found on PATH")
    if not _which("java"):
        pytest.skip("java executable not found on PATH")
    if not JAVA_JAR.exists() or any(
        os.stat(p).st_mtime > os.stat(JAVA_JAR).st_mtime
        for p in JAVA_DIR.rglob("*.java")
    ):
        subprocess.run(
            ["mvn", "-q", "package", "-DskipTests"],
            cwd=str(JAVA_DIR),
            check=True,
        )
    return JAVA_JAR


def canonical_json(obj) -> str:
    """Recursively sort dict keys and produce compact JSON (no whitespace)."""
    return json.dumps(
        obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def deep_equal(a, b) -> bool:
    """Deep equality for nested dict/list/scalar structures."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a.keys()) == set(b.keys()) and all(
            deep_equal(a[k], b[k]) for k in a.keys()
        )
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(
            deep_equal(x, y) for x, y in zip(a, b)
        )
    return a == b


def read_fixture(name: str) -> bytes:
    """Read a fixture file as raw bytes (UTF-8)."""
    return (FIXTURES_DIR / name).read_bytes()


def run_cli(binary: list[str], stdin_bytes: bytes, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a CLI subprocess with JSON bytes on stdin."""
    return subprocess.run(
        binary,
        input=stdin_bytes,
        capture_output=True,
        timeout=timeout,
    )
