"""ASGI 适配器测试的 Redis 可用性门禁（仅集成测试用）。

凭证不落仓库：默认指向无密码 URL，环境变量 ATLAS_RICHIE_RATE_LIMIT_REDIS_URL
提供完整 DSN。不可用或需要认证时干净 skip。
"""

from __future__ import annotations

import os

import pytest

from atlas_richie.testing.pytest_support import skip_unless_reachable

REDIS_URL = os.environ.get(
    "ATLAS_RICHIE_RATE_LIMIT_REDIS_URL",
    "redis://127.0.0.1:16379/0",
)


@pytest.fixture(scope="session")
def requires_redis() -> None:
    def _ready(url: str) -> bool:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3)
        try:
            return bool(client.ping())
        except Exception:  # noqa: BLE001 — 需要认证或不可达都视为不可用
            return False
        finally:
            client.close()

    skip_unless_reachable(
        REDIS_URL, "Redis", env_hint="ATLAS_RICHIE_RATE_LIMIT_REDIS_URL", probe=_ready
    )
