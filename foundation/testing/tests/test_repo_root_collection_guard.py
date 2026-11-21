"""Guard: a repository-wide pytest run must fail with an actionable message.

The repository cannot be collected in one pytest run: `sentinel-console` is an
independent project that is not installed into the platform workspace, and
several packages ship a `tests` directory that pytest prepend import mode
resolves to one top-level module name. The root `conftest.py` turns that into a
usage error with instructions instead of a wall of collection errors.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_PER_PACKAGE_TARGET = "foundation/testing/tests/test_testing_helpers.py"


def test_repository_wide_run_is_refused_with_instructions() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 4, output
    assert "not supported" in output
    assert "components/http/tests" in output


def test_per_package_run_is_still_allowed() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", _PER_PACKAGE_TARGET],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr