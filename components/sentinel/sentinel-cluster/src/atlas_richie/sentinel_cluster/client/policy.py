"""Atlas Richie Sentinel Cluster — ClusterFailurePolicy 决策 (M6.3.6 + M6.3.4).

中文
----
``RemoteTokenService.acquire`` 在以下情况按 per-resource
``ClusterFailurePolicy`` 决策:

- Server 不可达 (ConnectionRefusedError / OSError)
- Server 拒响应 (3 次 retry 后仍失败)
- 协议错 (PROTOCOL_VERSION_MISMATCH / MALFORMED_ENVELOPE / UNKNOWN_MESSAGE_KIND)
- Server 资源满 (SERVER_OVERLOADED)
- 内部错 (INTERNAL_ERROR retry 后仍失败)

**3 选 1 决策语义** (跟 ``ClusterFailurePolicy`` enum 一一对应):

- ``FAIL_CLOSED``: 强保证, 实际 grant 总量不得超出 Server 认定的配额。
  Client 收到失败 → 返回 ``TokenResponse(decision=DENIED,
  deny_reason=REMOTE_UNAVAILABLE)``, 业务受影响。
- ``FAIL_OPEN``: 不承诺不超发, 但每次放行必须产生可查询
  ``FAIL_OPEN`` 决策 + 指标。Client 收到失败 → 构造 stub token
  (``Token.lease_id=None`` 标记 stub), 返回 ``TokenResponse(decision=FAIL_OPEN)``。
- ``LOCAL_FALLBACK``: 显式本地策略 + 上限 + 恢复切换; **不**伪装为共享
  配额。Client 收到失败 → fallback 到 ``LocalTokenService`` (永远
  ``LOCAL_GRANTED``), 返回 ``TokenResponse(decision=LOCAL_GRANTED)``。

**STALE_EPOCH** 特殊处理: ``policy`` 模块**不**参与 (STALE_EPOCH
由调用方判定后直接 log warn + 忽略, 走业务正常 release / renew 路径)。

**反例** (1.0 拒绝):

- ❌ 引入 default policy (M6.3.6: 每个 resource 必须显式配)
- ❌ "auto" / "silent" / "inherit" 之类禁用值 (M6.3.6 决策)
- ❌ 跨 resource 共用 policy (每个 resource 独立)
- ❌ 在 policy 里抛异常 (policy 永远返回 TokenResponse, 不抛)

English
--------
``RemoteTokenService.acquire`` consults per-resource ``ClusterFailurePolicy``
when:

- Server unreachable (ConnectionRefusedError / OSError)
- Server not responding (3 retries exhausted)
- Protocol error (PROTOCOL_VERSION_MISMATCH / MALFORMED_ENVELOPE /
  UNKNOWN_MESSAGE_KIND)
- Server overload (SERVER_OVERLOADED)
- Internal error (INTERNAL_ERROR after retry)

**3-way decision semantics** (1:1 with ``ClusterFailurePolicy``):

- ``FAIL_CLOSED``: strong guarantee; total grants never exceed Server-admitted
  quota. Client failure → ``TokenResponse(decision=DENIED,
  deny_reason=REMOTE_UNAVAILABLE)``; business affected.
- ``FAIL_OPEN``: no over-grant promise, but every pass produces queryable
  ``FAIL_OPEN`` decision + metric. Client failure → stub token
  (``Token.lease_id=None`` to mark stub), ``TokenResponse(decision=FAIL_OPEN)``.
- ``LOCAL_FALLBACK``: explicit local policy + cap + recovery switch;
  **not** disguised as shared quota. Client failure → fallback to
  ``LocalTokenService`` (always ``LOCAL_GRANTED``), ``TokenResponse(decision=LOCAL_GRANTED)``.

**STALE_EPOCH** special: ``policy`` module **not** involved (caller detects
and log warns + ignores; business continues normal release / renew).

Anti-patterns (1.0 forbidden):

- ❌ Default policy (M6.3.6: each resource must be explicit)
- ❌ "auto" / "silent" / "inherit" (M6.3.6 disabled)
- ❌ Cross-resource shared policy (each resource independent)
- ❌ Raising in policy (policy always returns TokenResponse, never raises)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from atlas_richie.sentinel.ports.token import (
    ClusterFailurePolicy,
    LocalTokenService,
    Token,
    TokenDecision,
    TokenDenyReason,
    TokenResponse,
)

_log = logging.getLogger("atlas_richie.sentinel_cluster.client.policy")


# ---------------------------------------------------------------------------
# Decision context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """ClusterFailurePolicy 决策结果 (M6.3.4).

    Attributes:
        response: 给 ``acquire`` 同步 facade 的 ``TokenResponse``
        decision_kind: 决策类型 (用于指标 + 日志 + 调试)
        fail_open: 是否是 FAIL_OPEN 放行 (指标 + 审计)
        local_fallback: 是否走 LOCAL_FALLBACK fallback (指标 + 审计)
    """

    response: TokenResponse
    decision_kind: str = field(default="UNKNOWN")
    fail_open: bool = False
    local_fallback: bool = False


# ---------------------------------------------------------------------------
# 决策实现
# ---------------------------------------------------------------------------


def _stub_token(resource: str, permits: float, now_ns: int) -> Token:
    """构造 FAIL_OPEN stub token (lease_id=None 标记 stub)."""
    return Token(
        resource=resource,
        permits=permits,
        issued_at_ns=now_ns,
        ttl_ns=0,  # 永久 (本地 stub, 不参与 Server 协调)
        lease_id=None,  # M6.3.4: 标记 stub, 跟真 lease 区分
        owner_epoch=None,  # 无 Server 端 epoch 概念
    )


def decide_failure(
    *,
    resource: str,
    permits: float,
    policy: ClusterFailurePolicy,
    reason: str,
    local_fallback: LocalTokenService | None = None,
) -> PolicyDecision:
    """按 ``ClusterFailurePolicy`` 决策 Server 失败时的 ``TokenResponse``.

    Args:
        resource: 资源名
        permits: 申请 permit 数
        policy: per-resource 失败策略
        reason: 失败原因 (记 log warn, **不**含 secret / token)
        local_fallback: LOCAL_FALLBACK 时用的 ``LocalTokenService`` 实例
            (None → 1.0 stub: 退化为 FAIL_CLOSED 行为, 避免 silently fallback)

    Returns:
        ``PolicyDecision`` (含 ``TokenResponse`` + 决策类型标签)

    行为契约:

    - ``FAIL_CLOSED``: 永远 ``DENIED`` + ``REMOTE_UNAVAILABLE``,
      业务受影响. **不**需要 ``local_fallback`` 参数.
    - ``FAIL_OPEN``: 永远 ``FAIL_OPEN`` 决策 + stub token
      (``Token.lease_id=None`` 标记). **不**需要 ``local_fallback`` 参数.
    - ``LOCAL_FALLBACK``: 必须传 ``local_fallback``; 调
      ``local_fallback.acquire(resource, permits)`` 返回 ``LOCAL_GRANTED``.
      若 ``local_fallback is None`` → 1.0 降级到 FAIL_CLOSED 行为
      (避免 silently fallback, 1.0 接受限制).
    """
    if policy is ClusterFailurePolicy.FAIL_CLOSED:
        # 默认 (强保证): 真 deny
        _log.warning(
            "cluster.acquire.deny_fail_closed: resource=%s reason=%s",
            resource,
            reason,
        )
        return PolicyDecision(
            response=TokenResponse(
                decision=TokenDecision.DENIED,
                token=None,
                deny_reason=TokenDenyReason.REMOTE_UNAVAILABLE,
                wait_ns=0,
            ),
            decision_kind="FAIL_CLOSED",
            fail_open=False,
            local_fallback=False,
        )

    if policy is ClusterFailurePolicy.FAIL_OPEN:
        # 不承诺不超发: 构造 stub token (lease_id=None 标记 stub)
        now_ns = time.time_ns()
        _log.warning(
            "cluster.acquire.fail_open_stub: resource=%s reason=%s",
            resource,
            reason,
        )
        return PolicyDecision(
            response=TokenResponse(
                decision=TokenDecision.FAIL_OPEN,
                token=_stub_token(resource, permits, now_ns),
                deny_reason=None,
                wait_ns=0,
            ),
            decision_kind="FAIL_OPEN",
            fail_open=True,
            local_fallback=False,
        )

    if policy is ClusterFailurePolicy.LOCAL_FALLBACK:
        # 显式本地策略: fallback 到 LocalTokenService
        if local_fallback is None:
            # 1.0 接受限制: 没传 local_fallback → 降级 FAIL_CLOSED
            # (避免 silently fallback, 用户必须显式提供 fallback 实例)
            _log.warning(
                "cluster.acquire.fallback_missing_fail_closed: resource=%s reason=%s",
                resource,
                reason,
            )
            return PolicyDecision(
                response=TokenResponse(
                    decision=TokenDecision.DENIED,
                    token=None,
                    deny_reason=TokenDenyReason.REMOTE_UNAVAILABLE,
                    wait_ns=0,
                ),
                decision_kind="LOCAL_FALLBACK_MISSING",
                fail_open=False,
                local_fallback=True,
            )
        _log.warning(
            "cluster.acquire.local_fallback: resource=%s reason=%s",
            resource,
            reason,
        )
        return PolicyDecision(
            response=local_fallback.acquire(resource, permits),
            decision_kind="LOCAL_FALLBACK",
            fail_open=False,
            local_fallback=True,
        )

    # 不可达分支: 不在 3 选 1 显式 enum
    raise ValueError(
        f"unsupported ClusterFailurePolicy: {policy!r} (M6.3.6 3 选 1 决策)"
    )


__all__ = ["PolicyDecision", "decide_failure"]
