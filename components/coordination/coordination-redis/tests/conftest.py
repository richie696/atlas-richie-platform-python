"""Redis availability gate so the suite skips cleanly without a server."""

from __future__ import annotations

import os

import pytest

from atlas_richie.testing.pytest_support import skip_unless_reachable

DEFAULT_REDIS_URL = "redis://127.0.0.1:16379/0"
REDIS_URL = os.environ.get("ATLAS_RICHIE_COORDINATION_REDIS_URL", DEFAULT_REDIS_URL)


def _redis_ready(url: str) -> bool:
    """An open port is not enough: the server may require a password we lack."""
    import redis as redis_lib

    client = redis_lib.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
    try:
        return bool(client.ping())
    finally:
        client.close()


@pytest.fixture(scope="session")
def redis_url() -> str:
    return REDIS_URL


@pytest.fixture(scope="session")
def requires_redis(redis_url: str) -> None:
    skip_unless_reachable(
        redis_url, "Redis", env_hint="ATLAS_RICHIE_COORDINATION_REDIS_URL", probe=_redis_ready
    )


@pytest.fixture
def client(requires_redis: None, redis_url: str):
    import redis as redis_lib

    connection = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield connection
    finally:
        connection.close()
