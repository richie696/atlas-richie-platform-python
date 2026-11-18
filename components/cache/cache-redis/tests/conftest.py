"""`atlas-richie-cache-redis` test configuration (Phase C).

Provides:

1. **Automatic marker application** — any test in a file whose
   path contains `e2e` is marked `e2e`; otherwise it's marked
   `unit`. Tests can also be explicitly marked `integration`.
2. **Shared fixtures** — `redis_url`, `redis_registrar`,
   `redis_namespace` extracted from the duplicated boilerplate
   that previously lived in every test file.
3. **Redis availability check** — `requires_redis` fixture skips
   tests if the test Redis is unreachable (so unit-only runs
   on machines without Redis still pass).
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

from atlas_richie.testing import tcp_reachable

DEFAULT_REDIS_URL = "redis://127.0.0.1:16379/0"
REDIS_URL = os.environ.get("ATLAS_RICHIE_CACHE_REDIS_URL", DEFAULT_REDIS_URL)


def _is_redis_reachable(url: str) -> bool:
    """TCP reachability plus a PING: an auth-required server we cannot log into
    is reachable but unusable, and must skip rather than error every test."""
    if not tcp_reachable(url, default_port=6379):
        return False
    import redis as redis_lib

    client = redis_lib.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
    try:
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False
    finally:
        client.close()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-mark tests based on file path / explicit markers.

    - Files with `e2e` in path → `@pytest.mark.e2e`
    - All others → `@pytest.mark.unit` (unless explicitly marked
      `integration`)
    """
    for item in items:
        # If the user already marked this test, don't override.
        existing = {m.name for m in item.iter_markers()}
        if "integration" in existing:
            continue
        if "e2e" in existing:
            continue
        if "unit" in existing:
            continue
        path = str(item.fspath)
        if "e2e" in path:
            item.add_marker(pytest.mark.e2e)
        else:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def redis_url() -> str:
    """The Redis URL to use for all tests in this package.

    Reads `ATLAS_RICHIE_CACHE_REDIS_URL` from the environment;
    falls back to the project default. The test Redis is a
    project-local instance on port 16379 (not the default 6379
    port) so it doesn't collide with developer-side redis.
    """
    return REDIS_URL


@pytest.fixture(scope="session")
def redis_available(redis_url: str) -> bool:
    """Whether the test Redis is reachable on this machine."""
    return _is_redis_reachable(redis_url)


@pytest.fixture
def requires_redis(redis_available: bool) -> None:
    """Skip a test if the test Redis is unreachable.

    Usage:

        def test_something(requires_redis):
            # only runs if Redis is reachable
            ...
    """
    if not redis_available:
        pytest.skip(
            f"Redis not reachable at {REDIS_URL}; "
            "set ATLAS_RICHIE_CACHE_REDIS_URL or start the test Redis"
        )


@pytest.fixture(scope="session")
def requires_redis_session(redis_available: bool) -> None:
    """Session-scoped `requires_redis` for module/session-scoped fixtures.

    A module-scoped `registrar` fixture cannot depend on the function-scoped
    `requires_redis` (pytest raises ScopeMismatch), so real-Redis fixtures
    request this variant instead.
    """
    if not redis_available:
        pytest.skip(
            f"Redis not reachable at {REDIS_URL}; "
            "set ATLAS_RICHIE_CACHE_REDIS_URL or start the test Redis"
        )


@pytest.fixture(scope="module")
def redis_namespace() -> str:
    """A unique namespace per test session — prevents cross-test pollution."""
    return f"atlas-richie-test-{uuid.uuid4().hex[:8]}" if False else "atlas-richie-test"


# Local import to avoid name shadowing.
import uuid  # noqa: E402
