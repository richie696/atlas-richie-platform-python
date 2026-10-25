"""Execute the shared Rule Load Observation fixture corpus in Go and Java."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


def _run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed: {' '.join(command)}\n"
        f"stdout:\n{result.stdout[-4000:]}\n"
        f"stderr:\n{result.stderr[-4000:]}"
    )


def test_go_executes_shared_rule_load_observation_fixtures() -> None:
    if shutil.which("go") is None:
        pytest.skip("Go toolchain is required for cross-language conformance")
    _run(["go", "test", "./..."], _HERE / "go")


def test_java_executes_shared_rule_load_observation_fixtures() -> None:
    if shutil.which("mvn") is None or shutil.which("java") is None:
        pytest.skip("Maven and JDK are required for cross-language conformance")
    _run(["mvn", "-q", "test", "-Dfixture.dir=../fixtures"], _HERE / "java")
