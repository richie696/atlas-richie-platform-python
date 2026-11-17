"""Redis availability gate so the suite skips cleanly without a server."""

from __future__ import annotations

import os
import socket

import pytest

DEFAULT_REDIS_URL = "redis://:Redis2025!Local@127.0.0.1:16379/0"
REDIS_URL = os.environ.get("ATLAS_RICHIE_STREAMMQ_REDIS_URL", DEFAULT_REDIS_URL)


def _reachable(url: str) -> bool:
    try:
        rest = url.split("://", 1)[1]
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        host_port = rest.split("/", 1)[0]
        host, _, port = host_port.rpartition(":")
        with socket.create_connection((host or "127.0.0.1", int(port or 6379)), timeout=1.0):
            return True
    except (OSError, ValueError, IndexError):
        return False


@pytest.fixture(scope="session")
def redis_url() -> str:
    return REDIS_URL


@pytest.fixture(scope="session")
def requires_redis(redis_url: str) -> None:
    if not _reachable(redis_url):
        pytest.skip(f"Redis not reachable at {redis_url}; set ATLAS_RICHIE_STREAMMQ_REDIS_URL")


@pytest.fixture
def client(requires_redis: None, redis_url: str):
    import redis as redis_lib

    connection = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield connection
    finally:
        connection.close()
