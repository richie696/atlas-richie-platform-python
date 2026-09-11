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

## Usage

```bash
# Run only unit tests (fast, default for CI on PRs).
pytest -m unit

# Run unit + integration (skip e2e).
pytest -m "not e2e"

# Run only e2e.
pytest -m e2e

# Run all (default = no marker filter).
pytest
```

## Workspace-level fixtures

We do not define workspace-level fixtures here yet — each package
is a self-contained pytest rootdir and has its own `tests/conftest.py`.
Add workspace-level fixtures here only if they're needed by 2+
packages; otherwise colocate with the consumer tests.
"""

from __future__ import annotations

import pytest


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
