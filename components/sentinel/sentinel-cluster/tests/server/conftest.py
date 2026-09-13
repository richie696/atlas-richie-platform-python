"""conftest.py for sentinel-cluster server tests (M6.3.3 + M6.3.5).

中文
----
Server 端单测的公共 fixture / helper:

- ``fake_clock`` — 注入时间, 避免 ``time.time_ns()`` 跳变
- ``base_config`` — 最小合法 ``ClusterTokenConfig`` (1 resource)
- ``multi_resource_config`` — 多个 resource 的 config
- ``make_envelope`` — 构造 envelope (单测 helper)

**测试策略**:

- 全部单测, 0 网络 (HTTP transport 仅在 worker 2 / M6.4 跑)
- 用 ``pytest-asyncio`` 严格模式, 每个 async test 标 ``@pytest.mark.asyncio``
- 注入 clock 让 TTL 行为可测

English
--------
Shared fixtures / helpers for Server unit tests:

- ``fake_clock`` — injected time to avoid ``time.time_ns()`` jumps
- ``base_config`` — minimal legal ``ClusterTokenConfig`` (1 resource)
- ``multi_resource_config`` — config with multiple resources
- ``make_envelope`` — construct envelope (test helper)
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import pytest

from atlas_richie.contracts.cluster.v1 import (
    ClusterMessageKind,
    ClusterTokenEnvelope,
    ISO_8601_UTC_MICRO,
    PROTOCOL_VERSION,
)
from atlas_richie.sentinel.ports.token import ClusterFailurePolicy

from atlas_richie.sentinel_cluster.config import (
    ClusterTokenConfig,
    ClusterTokenMode,
    ResourceConfig,
)


@pytest.fixture
def fake_clock() -> "list[int]":
    """可注入的 fake clock (单测用).

    Returns:
        list with 1 element, mutable, fake "now_ns" value
    """
    return [int(time.time_ns())]


@pytest.fixture
def advance_clock(fake_clock: "list[int]") -> Callable[[int], None]:
    """推进 fake_clock 给定纳秒数 (单测 helper)."""

    def _advance(ns: int) -> None:
        fake_clock[0] += ns

    return _advance


def _now_iso(now_ns: int) -> str:
    dt = datetime.fromtimestamp(now_ns / 1_000_000_000, tz=timezone.utc)
    return dt.strftime(ISO_8601_UTC_MICRO)


def make_envelope(
    *,
    message_kind: ClusterMessageKind,
    resource: str = "/api/v1/users",
    permits: float = 1.0,
    request_id: str | None = None,
    instance_id: str | None = None,
    startup_epoch: int = 0,
    deadline_ns: int = 5_000_000,
    payload: dict[str, Any] | None = None,
    now_ns: int | None = None,
) -> ClusterTokenEnvelope:
    """构造 envelope (单测 helper)."""
    if request_id is None:
        request_id = str(uuid.uuid4())
    if instance_id is None:
        instance_id = str(uuid.uuid4())
    if now_ns is None:
        now_ns = time.time_ns()
    iso = _now_iso(now_ns)
    if payload is None:
        payload = {}
    return ClusterTokenEnvelope(
        protocol_version=PROTOCOL_VERSION,
        message_kind=message_kind,
        request_id=request_id,
        instance_id=instance_id,
        startup_epoch=startup_epoch,
        resource=resource,
        permits=permits,
        deadline_ns=deadline_ns,
        client_requested_at=iso,
        server_received_at=iso,
        payload=payload,
    )


@pytest.fixture
def base_config(fake_clock: "list[int]") -> ClusterTokenConfig:
    """最小合法 ClusterTokenConfig (1 resource, standalone 模式)."""
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address="127.0.0.1:0",
        auth_secret="test-secret-001",
        resources=(ResourceConfig(name="/api/v1/users", max_permits=10.0),),
        failure_policy_per_resource={
            "/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED,
        },
    )


@pytest.fixture
def multi_resource_config(fake_clock: "list[int]") -> ClusterTokenConfig:
    """多 resource 的 ClusterTokenConfig."""
    return ClusterTokenConfig(
        cluster_token_mode=ClusterTokenMode.STANDALONE,
        bind_address="127.0.0.1:0",
        auth_secret="test-secret-multi",
        resources=(
            ResourceConfig(name="/api/v1/users", max_permits=10.0),
            ResourceConfig(name="/api/v1/orders", max_permits=5.0),
        ),
        failure_policy_per_resource={
            "/api/v1/users": ClusterFailurePolicy.FAIL_CLOSED,
            "/api/v1/orders": ClusterFailurePolicy.FAIL_OPEN,
        },
    )


@pytest.fixture
def make_acquire_envelope() -> Callable[..., ClusterTokenEnvelope]:
    """构造 ACQUIRE_REQUEST envelope (单测 helper)."""

    def _factory(
        *,
        resource: str = "/api/v1/users",
        permits: float = 1.0,
        instance_id: str | None = None,
        startup_epoch: int = 0,
        request_id: str | None = None,
        now_ns: int | None = None,
        rule_version_epoch: int = 1,
        rule_version_revision: int = 0,
        rule_version_checksum: str = "sha256:" + "a" * 64,
        priority: int = 0,
    ) -> ClusterTokenEnvelope:
        return make_envelope(
            message_kind=ClusterMessageKind.ACQUIRE_REQUEST,
            resource=resource,
            permits=permits,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            request_id=request_id,
            now_ns=now_ns,
            payload={
                "rule_version_epoch": rule_version_epoch,
                "rule_version_revision": rule_version_revision,
                "rule_version_checksum": rule_version_checksum,
                "priority": priority,
            },
        )

    return _factory


@pytest.fixture
def make_release_envelope() -> Callable[..., ClusterTokenEnvelope]:
    """构造 RELEASE_REQUEST envelope (单测 helper)."""

    def _factory(
        *,
        lease_id: str,
        permits_released: float = 1.0,
        instance_id: str | None = None,
        startup_epoch: int = 0,
        request_id: str | None = None,
        resource: str = "/api/v1/users",
    ) -> ClusterTokenEnvelope:
        return make_envelope(
            message_kind=ClusterMessageKind.RELEASE_REQUEST,
            resource=resource,
            permits=permits_released,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            request_id=request_id,
            payload={
                "lease_id": lease_id,
                "permits_released": permits_released,
            },
        )

    return _factory


@pytest.fixture
def make_renew_envelope() -> Callable[..., ClusterTokenEnvelope]:
    """构造 RENEW_REQUEST envelope (单测 helper)."""

    def _factory(
        *,
        lease_id: str,
        extends_for_ns: int = 5_000_000_000,
        instance_id: str | None = None,
        startup_epoch: int = 0,
        request_id: str | None = None,
        resource: str = "/api/v1/users",
    ) -> ClusterTokenEnvelope:
        return make_envelope(
            message_kind=ClusterMessageKind.RENEW_REQUEST,
            resource=resource,
            instance_id=instance_id,
            startup_epoch=startup_epoch,
            request_id=request_id,
            payload={
                "lease_id": lease_id,
                "extends_for_ns": extends_for_ns,
            },
        )

    return _factory
