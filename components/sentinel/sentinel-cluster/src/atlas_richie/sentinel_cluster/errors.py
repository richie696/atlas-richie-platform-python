"""Atlas Richie Sentinel Cluster — Server 端异常层 (M6.3.3 + M6.3.5).

中文
----
``sentinel-cluster`` wheel 的 Server 端异常类型。**全部**继承主包
``SentinelError``, 不重新定义根异常, 跟 M0.5-A 单一异常层治理一致。

错误类型 (1.0 公开, 跟 M6.3 design §2.3 公开 API surface 一致):

- ``ClusterServerError`` — 所有 Server 端异常的基类
- ``ClusterConfigError`` — 配置错误 (resource 未配 / mode 错误 / 鉴权缺 secret)
- ``ClusterLeaseNotFound`` — release / renew 时 lease_id 不存在
- ``ClusterLeaseExpired`` — renew 时 lease 已过期
- ``ClusterStaleEpoch`` — owner epoch 不匹配 (Client 忽略, 不抛)
- ``ClusterResourceNotConfigured`` — acquire 时 resource 未配
- ``ClusterServerOverloaded`` — Server 资源满

**单一异常层** (M0.5-A 治理 + M1.1 review 决策): Cluster 异常**直接**
继承 ``SentinelError``, 不走 ``SentinelBlockedError`` / ``SentinelLifecycleError``
中间层。原因: Cluster 异常是 Server 端内部故障, 跟 Engine / Slot 拒绝路径
是独立分支。

English
--------
Server-side exception types for the ``sentinel-cluster`` wheel (M6.3.3 + M6.3.5).

All exceptions inherit the main-wheel ``SentinelError`` directly per the
M0.5-A single-exception-layer discipline. No redefinition of the root
exception.

Exception hierarchy (1.0 public, matches M6.3 design §2.3 public API surface):

- ``ClusterServerError`` — base for all Server-side exceptions
- ``ClusterConfigError`` — config errors (resource unconfigured / mode / auth)
- ``ClusterLeaseNotFound`` — release / renew with unknown lease_id
- ``ClusterLeaseExpired`` — renew on already-expired lease
- ``ClusterStaleEpoch`` — owner epoch mismatch (Client ignores, no raise)
- ``ClusterResourceNotConfigured`` — acquire on unconfigured resource
- ``ClusterServerOverloaded`` — Server resource exhausted

Single exception layer (M0.5-A + M1.1 review): Cluster exceptions inherit
``SentinelError`` directly, **not** via ``SentinelBlockedError`` or
``SentinelLifecycleError``. Rationale: Cluster exceptions are Server-internal
faults; they live in a separate branch from Engine / Slot rejection paths.
"""

from __future__ import annotations

from atlas_richie.sentinel.errors.base import SentinelError


class ClusterServerError(SentinelError):
    """所有 Cluster Server 端异常的基类 (1.0 公开)."""

    def __init__(self, message: str = "", *, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ClusterConfigError(ClusterServerError):
    """配置错误 (启动 fail-fast).

    触发场景:
    - ``failure_policy_per_resource`` 缺 key (resource 未配)
    - 启动形态校验失败 (embedded 多 worker / standalone 缺 bind)
    - 鉴权 secret 为空
    """

    def __init__(self, message: str = "", *, code: str = "CONFIG_ERROR") -> None:
        super().__init__(message, code=code)


class ClusterLeaseNotFound(ClusterServerError):
    """Release / Renew 时 ``lease_id`` 在 store 中不存在."""

    def __init__(self, message: str = "lease not found", *, code: str = "LEASE_NOT_FOUND") -> None:
        super().__init__(message, code=code)


class ClusterLeaseExpired(ClusterServerError):
    """Renew 时 ``lease_id`` 已过期 (Server 决定)."""

    def __init__(self, message: str = "lease expired", *, code: str = "LEASE_EXPIRED") -> None:
        super().__init__(message, code=code)


class ClusterStaleEpoch(ClusterServerError):
    """Owner epoch 不匹配 (fencing).

    **Client 收到不抛异常, 仅 log warn** (正常 race 现象, 设计 §4.3).
    在 Server 端, release / renew 校验失败时**返回** ``STALE_EPOCH``
    错误码 (Client 决定怎么处理), 不在 Server 端内部抛。
    本类用于 Server 启动 / 内部 invariant 校验失败场景。
    """

    def __init__(self, message: str = "stale epoch", *, code: str = "STALE_EPOCH") -> None:
        super().__init__(message, code=code)


class ClusterResourceNotConfigured(ClusterServerError):
    """Acquire 时 resource 未在 ``ClusterTokenConfig.failure_policy_per_resource`` 中配置.

    启动时已 fail-fast; 运行时再次校验是 defence-in-depth。
    """

    def __init__(self, message: str = "resource not configured", *, code: str = "RESOURCE_NOT_CONFIGURED") -> None:
        super().__init__(message, code=code)


class ClusterServerOverloaded(ClusterServerError):
    """Server 资源满, 返回 DENIED + ``deny_reason=SERVER_OVERLOADED``."""

    def __init__(self, message: str = "server overloaded", *, code: str = "SERVER_OVERLOADED") -> None:
        super().__init__(message, code=code)


__all__ = [
    "ClusterServerError",
    "ClusterConfigError",
    "ClusterLeaseNotFound",
    "ClusterLeaseExpired",
    "ClusterStaleEpoch",
    "ClusterResourceNotConfigured",
    "ClusterServerOverloaded",
]
