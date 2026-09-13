"""Shared fixtures for real-Nacos integration tests (M6.1.7d).

中文
----
本 conftest 集中管理跨多个集成测试文件复用的资源:

- **真实 Nacos 地址**: ``nacos_url`` / ``nacos_user`` / ``nacos_password``
  (env var, 默认 ``127.0.0.1:8848`` / ``nacos`` / ``nacos``)。
  集成测试在真 Nacos (本机 Docker ``nacos-pg-3.2.3``, 端口 8848+9848)
  上跑 M6.1.7 真实验收 5 场景; 不可达时整个集成套件自动 skip
  (跟 cache-redis 单元测试保持一致)。
- **Nacos SDK admin client**: ``nacos_admin_client`` (真实 ``NacosConfigService``)
  用于 publish/delete 测试数据; 测试结束 teardown 时按 data_id 删。
- **测试 namespace 隔离**: ``nacos_namespace`` (per-module, 唯一 hex),
  所有写入限定在该 namespace 下, 避免跟其他测试 / 真实数据冲突。
- **NacosRuleSource 构造**: ``nacos_rule_source`` factory helper。

English
--------
Workspace-level shared fixtures for the real-Nacos integration suite
(M6.1.7d). Provides:

- **Real Nacos endpoint**: ``nacos_url`` / ``nacos_user`` / ``nacos_password``
  (env-overridable). Integration tests run against a real Nacos 3.2.3
  server; unreachable → entire suite skips.
- **Nacos SDK admin client**: ``nacos_admin_client`` (real
  ``NacosConfigService``) for publishing/deleting test fixtures.
- **Test namespace**: ``nacos_namespace`` (unique hex per module) so
  tests cannot collide with each other or real configs.
- **NacosRuleSource factory**: ``nacos_rule_source`` builds a configured
  source pointing at the test namespace.
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

from atlas_richie.sentinel_source_nacos import (
    NacosAuth,
    NacosRuleSource,
    NacosRuleSourceConfig,
    NacosSourceState,
)


# ---------------------------------------------------------------------------
# Real-Nacos reachability
# ---------------------------------------------------------------------------

DEFAULT_NACOS_URL = "127.0.0.1:8848"
DEFAULT_NACOS_USER = "nacos"
DEFAULT_NACOS_PASSWORD = "nacos"

NACOS_URL = os.environ.get("ATLAS_RICHIE_SENTINEL_NACOS_URL", DEFAULT_NACOS_URL)
NACOS_USER = os.environ.get("ATLAS_RICHIE_SENTINEL_NACOS_USER", DEFAULT_NACOS_USER)
NACOS_PASSWORD = os.environ.get(
    "ATLAS_RICHIE_SENTINEL_NACOS_PASSWORD", DEFAULT_NACOS_PASSWORD
)


def _is_nacos_reachable(url: str) -> bool:
    """Quick TCP probe for the test Nacos. Mirrors the cache-redis
    ``conftest.py`` helper so the integration suite skips cleanly when
    no test Nacos is available.
    """
    try:
        host, port = url.rsplit(":", 1)
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def nacos_url() -> str:
    """Nacos HTTP address for the integration suite (env-overridable)."""
    return NACOS_URL


@pytest.fixture(scope="session")
def nacos_user() -> str:
    return NACOS_USER


@pytest.fixture(scope="session")
def nacos_password() -> str:
    return NACOS_PASSWORD


@pytest.fixture(scope="session")
def nacos_available(nacos_url: str) -> bool:
    """Whether the test Nacos is reachable on this machine."""
    return _is_nacos_reachable(nacos_url)


@pytest.fixture(scope="module")
def requires_nacos(nacos_available: bool, nacos_url: str) -> None:
    """Skip a module if the test Nacos is unreachable.

    Module-scoped (not function-scoped) because ``nacos_admin_client`` is
    module-scoped and pulls this in. Mirrors the cache-redis convention.
    """
    if not nacos_available:
        pytest.skip(
            f"Nacos not reachable at {nacos_url}; "
            f"set ATLAS_RICHIE_SENTINEL_NACOS_URL or start a Nacos server"
        )


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def nacos_namespace() -> str:
    """Unique per-module namespace id. Used as the Nacos namespace for
    isolation so one test module cannot collide with another.
    """
    return f"atlas-richie-int-{uuid.uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def nacos_admin_client(
    requires_nacos: None,
    nacos_url: str,
    nacos_user: str,
    nacos_password: str,
    nacos_namespace: str,
) -> AsyncIterator[Any]:
    """Real ``NacosConfigService`` for publishing/deleting test fixtures.

    中文
    ----
    Function-scoped (per-test) because ``nacos-sdk-python`` 3.2.0 的 gRPC
    client 绑定到构造时的 event loop, module scope 会导致
    ``attached to a different loop`` 错误 (test 跑在 test function 的 loop,
    admin client 跑在 module fixture 的 loop)。

    测试用 ``admin.publish_config(...)`` / ``admin.remove_config(...)``
    增删 data_id; teardown 自动 shutdown。
    """
    svc = await create_ready_nacos_config_service(
        nacos_url=nacos_url,
        nacos_user=nacos_user,
        nacos_password=nacos_password,
        nacos_namespace=nacos_namespace,
    )
    try:
        yield svc
    finally:
        try:
            await svc.shutdown()
        except Exception:
            pass


async def create_nacos_config_service(
    *,
    nacos_url: str,
    nacos_user: str,
    nacos_password: str,
    nacos_namespace: str,
) -> Any:
    """Create one SDK config service bound to the current asyncio loop."""
    from v2.nacos import ClientConfigBuilder, GRPCConfig, NacosConfigService

    grpc_config = GRPCConfig(port_offset=1000, grpc_timeout=10000)
    client_config = (
        ClientConfigBuilder()
        .server_address(nacos_url)
        .namespace_id(nacos_namespace)
        .username(nacos_user)
        .password(nacos_password)
        .grpc_config(grpc_config)
        .timeout_ms(10000)
        .build()
    )
    return await NacosConfigService.create_config_service(client_config)


async def create_ready_nacos_config_service(
    *,
    nacos_url: str,
    nacos_user: str,
    nacos_password: str,
    nacos_namespace: str,
    timeout_seconds: float = 30.0,
) -> Any:
    """Return a config service only after an authenticated config read works.

    A listening TCP port is insufficient after a Nacos restart: the HTTP
    endpoint can be open while the authentication and gRPC config services
    are still initializing.  A read of a unique missing data-id is
    side-effect free and proves the exact control-plane capability the tests
    need.
    """
    from v2.nacos.config.model.config_param import ConfigParam

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    last_error: Exception | None = None
    readiness_data_id = f"atlas-richie-readiness-{uuid.uuid4().hex}"
    while loop.time() < deadline:
        service = await create_nacos_config_service(
            nacos_url=nacos_url,
            nacos_user=nacos_user,
            nacos_password=nacos_password,
            nacos_namespace=nacos_namespace,
        )
        try:
            await service.get_config(
                ConfigParam(data_id=readiness_data_id, group="DEFAULT_GROUP")
            )
            return service
        except Exception as error:
            last_error = error
            try:
                await service.shutdown()
            except Exception:
                pass
            await asyncio.sleep(1.0)
    raise RuntimeError(
        "Nacos config service did not become ready within "
        f"{timeout_seconds:.0f}s: {last_error!r}"
    )


# ---------------------------------------------------------------------------
# Per-test helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def data_id_prefix(nacos_namespace: str) -> str:
    """Per-test ``data_id_prefix`` (用于 NacosRuleSourceConfig).
    跟 ``nacos_namespace`` 共享 module scope uuid hex 8 字符, 但每 test
    function 又附加一个 8 字符 function-unique suffix, 保证 4 个 test
    function 写在同一个 module namespace 下 data_id 不冲突。
    """
    module_suffix = nacos_namespace.split("atlas-richie-int-", 1)[-1]
    func_suffix = uuid.uuid4().hex[:8]
    return f"atlas-richie-int-{module_suffix}-{func_suffix}"


def make_config(
    *,
    nacos_url: str,
    nacos_user: str,
    nacos_password: str,
    nacos_namespace: str,
    data_id_prefix: str,
    poll_interval_seconds: float = 1.0,
) -> NacosRuleSourceConfig:
    """构造一个 NacosRuleSourceConfig, 指向测试 namespace + 短 polling 间隔。"""
    return NacosRuleSourceConfig(
        source_id=f"int-{data_id_prefix}",
        server_addresses=(nacos_url,),
        namespace=nacos_namespace,
        group="DEFAULT_GROUP",
        data_id_prefix=data_id_prefix,
        auth=NacosAuth(username=nacos_user, password=nacos_password),
        poll_interval=__import__("datetime").timedelta(seconds=poll_interval_seconds),
    )


async def collect_first_snapshot(
    src: NacosRuleSource,
    *,
    timeout: float = 5.0,
) -> Any:
    """从 ``src.snapshots()`` 拿第一个 snapshot, 超时抛 TimeoutError。"""
    async def _drive() -> Any:
        async for s in src.snapshots():
            return s
        return None
    return await asyncio.wait_for(_drive(), timeout=timeout)


__all__ = [
    "DEFAULT_NACOS_URL",
    "DEFAULT_NACOS_USER",
    "DEFAULT_NACOS_PASSWORD",
    "NACOS_URL",
    "NACOS_USER",
    "NACOS_PASSWORD",
    "NacosSourceState",
    "create_nacos_config_service",
    "create_ready_nacos_config_service",
    "make_config",
    "collect_first_snapshot",
]
