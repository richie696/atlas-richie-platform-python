"""Root pytest configuration for the `atlas-richie-platform-python` workspace.

`pytest` discovers this `conftest.py` before any test collection,
so the test markers below are registered for the whole workspace.

## Test markers (Phase C)

- `unit` — fast, no I/O, no external dependencies. Runs in < 1s.
  Default marker for all tests in `components/*/tests/` and
  `foundation/*/tests/`.

- `integration` — multi-component or cross-component interaction.
  May use the real Redis test instance (see `ATLAS_RICHIE_TEST_REDIS_URL`)
  but does NOT spin up servers. Typical: cache + oauth handshake,
  cache + http client request.

- `e2e` — end-to-end, may spin up servers, may take many seconds.
  Typical: `test_e2e_real_redis.py` (real Redis), http server boot
  + real client call, mcp stdio + real tool invocation, oauth
  full flow.

## Repository-wide collection guard

`pytest` invoked at the repository root (no path argument) is refused with a
usage error that names the per-package invocations. A repository-wide run
cannot collect: `sentinel-console` is an independent project (own lock file,
own virtual environment) and is not installed into the platform workspace, and
several packages ship a `tests` directory that pytest prepend import mode
resolves to one top-level module name. Every per-package run is untouched.

## Usage

Each package is its own pytest rootdir, so run the suites **per package**:

```bash
# From the repository root, target one package.
uv run python -m pytest components/http/tests -q
uv run python -m pytest components/cache -q

# From inside a package directory.
cd components/http && uv run python -m pytest -q

# Marker filters work the same way, per package.
pytest -m unit
pytest -m "not e2e"
```

## Workspace-level fixtures

We do not define workspace-level fixtures here yet — each package
is a self-contained pytest rootdir and has its own `tests/conftest.py`.
Add workspace-level fixtures here only if they're needed by 2+
packages; otherwise colocate with the consumer tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parent


def _collection_root(arguments: list[str]) -> Path:
    """Return the directory a pytest invocation would collect from."""
    if not arguments:
        return Path.cwd().resolve()
    resolved = [Path(argument).resolve() for argument in arguments]
    return Path(os.path.commonpath([str(path) for path in resolved]))


def pytest_collection(session: pytest.Session) -> None:
    """Refuse a whole-repository collection and say how to run the suites."""
    if _collection_root(list(session.config.args)) != _REPOSITORY_ROOT:
        return
    raise pytest.UsageError(
        "Collecting the whole repository in one pytest run is not supported: "
        "sentinel-console is an independent project (own lock file, own virtual "
        "environment) and is not installed into the platform workspace, and "
        "several packages ship a `tests` directory that pytest prepend import "
        "mode resolves to one top-level module name. Run one package or "
        "project at a time, for example:\n"
        "  uv run python -m pytest components/http/tests -q\n"
        "  uv run python -m pytest foundation/testing/tests -q\n"
        "  (cd components/sentinel/sentinel-console && uv run --locked "
        "--extra test python -m pytest -q)"
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register workspace-level test markers.

    Without this, `pytest -m unit` warns about an unknown marker
    and treats the filter as a no-op. With it, the markers are
    first-class and the warning goes away.
    """
    config.addinivalue_line(
        "markers",
        "unit: fast tests with no I/O, no external dependencies (default)",
    )
    config.addinivalue_line(
        "markers",
        "integration: multi-component interaction, may use real Redis",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests that may spin up servers, slower",
    )
