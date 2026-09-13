"""Sentinel TokenService Port + 值对象(M2.7)。

中文
----
``TokenService`` 是 Cluster 模式下跨进程协调限流的 Port;1.0 主包
**不**拉任何集群依赖,提供 ``LocalTokenService`` 默认实现,所有
acquire 永远 grant(单进程不需要 token 协调)。

设计要点(PLANNING §M2.7 + 用户 P1 收口):

- **decision / deny_reason 拆分**:``TokenDecision``(4 选 1)+ ``TokenDenyReason``
  (5 选 1,无 AUTHORITY_DENIED,授权拒绝走 ``AuthoritySlot`` +
  ``AuthorityDenied``)+ ``TokenResponse`` frozen slots
- **强制不变量** (``__post_init__``):DENIED 必有 deny_reason +
  token=None;三种放行必有 token + deny_reason=None
- **永不暴露裸字符串**:decision / deny_reason 必传 StrEnum 成员
- **FAIL_OPEN ≠ LOCAL_GRANTED**:正常单进程 ``LocalTokenService.acquire()``
  走 ``LOCAL_GRANTED``(可观察);集群远端不可达降级才用 ``FAIL_OPEN``
  (标降级事件)
- **None 的合法用法**:``deny_reason=None`` 表示"无拒绝原因",不是
  "原因未知";``UNKNOWN`` 是真存在但不可分类

**M6.3.2 兼容扩展** (1.0 兼容, 仅加 optional field):

- ``Token`` 加 ``lease_id`` (Server opaque identity) + ``owner_epoch``
  (fencing), 默认 ``None``, ``LocalTokenService`` 永远不填, 旧构造方式
  兼容
- ``TokenResponse`` 加 ``retry_after_ns`` (Server 建议重试延迟), 默认 0
- ``ClusterFailurePolicy`` 3 选 1 enum (FAIL_CLOSED / FAIL_OPEN /
  LOCAL_FALLBACK), 每个集群资源显式选 1 项, 禁止默认静默放行

English
--------
Sentinel TokenService Port + value objects (M2.7).

``TokenService`` is the Port for cluster-mode cross-process limit
coordination; 1.0 main wheel pulls **no** cluster deps; provides
``LocalTokenService`` default impl where acquire always grants
(single-process doesn't need token coordination).

Design points (PLANNING §M2.7 + user P1 lock-in):

- **decision / deny_reason separation**: ``TokenDecision`` (4-way) +
  ``TokenDenyReason`` (5-way, no AUTHORITY_DENIED — authority goes
  through ``AuthoritySlot`` + ``AuthorityDenied``) + ``TokenResponse``
  frozen slots.
- **Enforced invariants** (``__post_init__``): DENIED requires
  ``deny_reason`` + ``token=None``; the 3 grants require ``token`` +
  ``deny_reason=None``.
- **Never bare strings**: ``decision`` / ``deny_reason`` must be
  StrEnum members.
- **FAIL_OPEN ≠ LOCAL_GRANTED**: normal single-process
  ``LocalTokenService.acquire()`` goes ``LOCAL_GRANTED`` (observable);
  cluster fallback uses ``FAIL_OPEN`` (labeled as degradation event).
- **None semantics**: ``deny_reason=None`` = "no reject reason", not
  "reason unknown"; ``UNKNOWN`` = real but uncategorized.

**M6.3.2 backward-compatible extension** (1.0 compat, optional field only):

- ``Token`` adds ``lease_id`` (Server opaque identity) + ``owner_epoch``
  (fencing); default ``None``; ``LocalTokenService`` never sets them;
  old construction form stays valid
- ``TokenResponse`` adds ``retry_after_ns`` (Server-suggested retry delay);
  default 0
- ``ClusterFailurePolicy`` 3-way enum (FAIL_CLOSED / FAIL_OPEN /
  LOCAL_FALLBACK); each cluster resource explicitly chooses 1; default
  silent pass is forbidden
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional, Protocol, runtime_checkable


class TokenDecision(StrEnum):
    """中文
    ----
    Token 获取决策(4 选 1)。

    English
    --------
    Token acquisition decision (4-way).
    """

    LOCAL_GRANTED = "local_granted"     # 本地默认实现直接放行
    REMOTE_GRANTED = "remote_granted"   # 集群 token 服务返回 permit
    FAIL_OPEN = "fail_open"             # 远端不可达,本地策略性放行(降级事件)
    DENIED = "denied"                    # 拒绝(配合 deny_reason)


class TokenDenyReason(StrEnum):
    """中文
    ----
    Token 拒绝原因(5 选 1)。

    **不**含 AUTHORITY_DENIED — 授权拒绝由 ``AuthoritySlot`` +
    ``AuthorityDenied`` 表达,不属于 TokenService。

    English
    --------
    Token deny reason (5-way).

    **Excludes** AUTHORITY_DENIED — authority rejection lives in
    ``AuthoritySlot`` + ``AuthorityDenied``, not TokenService.
    """

    QUEUE_FULL = "queue_full"
    REMOTE_UNAVAILABLE = "remote_unavailable"
    RATE_LIMITED = "rate_limited"
    SHUTTING_DOWN = "shutting_down"
    UNKNOWN = "unknown"


class ClusterFailurePolicy(StrEnum):
    """中文
    ----
    Cluster 资源 acquire 失败时的策略 (M6.3.6)。

    每个集群资源**必须**显式选择 1 项;**禁止**默认静默放行
    (PLANNING §M6.3 验收不变量)。

    三选一:

    - ``FAIL_CLOSED``: 实际 grant 总量不得超出 Server 认定的配额
      (强保证)。**真**deny, 业务受影响。
    - ``FAIL_OPEN``: 不承诺不超发, 但每次放行都必须产生可查询
      ``FAIL_OPEN`` 决策 + 指标。可能超发。
    - ``LOCAL_FALLBACK``: 显式配置本地策略 + 上限 + 恢复切换;
      **不**伪装为共享配额, 多实例不一致。

    详细语义见 ``docs/M6.3-CLUSTER-TOKEN-DESIGN.md`` §4 + §5.

    English
    --------
    Cluster resource acquire-failure policy (M6.3.6).

    Each cluster resource **must** explicitly choose 1;
    **forbidden** to default to silent pass (PLANNING §M6.3 invariants).

    Three options:

    - ``FAIL_CLOSED``: actual grant total never exceeds Server-admitted
      quota (strong guarantee). Real deny; business affected.
    - ``FAIL_OPEN``: no over-grant promise, but every pass produces
      a queryable ``FAIL_OPEN`` decision + metric. May over-grant.
    - ``LOCAL_FALLBACK``: explicitly configured local policy + cap +
      recovery switch; **not** disguised as shared quota; multi-instance
      inconsistent.

    Full semantics: ``docs/M6.3-CLUSTER-TOKEN-DESIGN.md`` §4 + §5.
    """

    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"
    LOCAL_FALLBACK = "local_fallback"


@dataclass(frozen=True, slots=True)
class Token:
    """中文
    ----
    Token 句柄(frozen slots)。FlowSlot 在 release 时归还给
    TokenService;LocalTokenService.noop 即可。

    M6.3.2 加 2 个 optional field (1.0 兼容, 安全默认值):

    - ``lease_id``: Server 生成的 opaque lease identity (UUID); Client
      不能伪造, 仅 Server 知道 mapping。**1.0 主包 LocalTokenService
      永远不填** (默认 ``None``)。
    - ``owner_epoch``: owner 进程的 startup_epoch, 用于 fencing (旧
      epoch 迟到 release / renew 不影响新 epoch)。**1.0 主包
      LocalTokenService 永远不填** (默认 ``None``)。

    旧构造方式 ``Token(resource=..., permits=..., issued_at_ns=..., ttl_ns=...)``
    仍 work (新字段用默认值, **不**破坏 1.0 兼容)。

    English
    --------
    Token handle (frozen slots). FlowSlot returns the token on
    release; ``LocalTokenService`` no-ops.

    M6.3.2 adds 2 optional fields (1.0 compat, safe defaults):

    - ``lease_id``: Server-generated opaque lease identity (UUID);
      Client cannot forge, only Server knows the mapping. **1.0
      main-wheel ``LocalTokenService`` never sets it** (default
      ``None``).
    - ``owner_epoch``: owner's startup_epoch, for fencing (stale
      release / renew from old epoch cannot affect new epoch). **1.0
      main-wheel ``LocalTokenService`` never sets it** (default
      ``None``).

    Old construction form ``Token(resource=..., permits=..., issued_at_ns=..., ttl_ns=...)``
    still works (new fields use defaults, **no** 1.0 compat break).
    """

    resource: str
    permits: float
    issued_at_ns: int
    ttl_ns: int
    # M6.3.2: opaque lease identity (Server 端 UUID, 1.0 主包永远 None)
    lease_id: Optional[str] = None
    # M6.3.2: owner epoch (fencing, 1.0 主包永远 None)
    owner_epoch: Optional[int] = None

    def is_expired(self, now_ns: int) -> bool:
        """中文
        ----
        是否过期;``ttl_ns == 0`` 表示永久。

        English
        --------
        Whether expired; ``ttl_ns == 0`` means forever.
        """
        if self.ttl_ns == 0:
            return False
        return now_ns - self.issued_at_ns > self.ttl_ns


@dataclass(frozen=True, slots=True)
class TokenResponse:
    """中文
    ----
    Token 服务的响应(frozen slots,带强制不变量)。

    不变量(``__post_init__`` 校验):

    - ``DENIED``: ``token is None`` + ``deny_reason is not None``
    - 三种放行(``LOCAL_GRANTED`` / ``REMOTE_GRANTED`` / ``FAIL_OPEN``):
      ``token is not None`` + ``deny_reason is None``

    ``wait_ns`` 是 0(= 立即)或 > 0(建议等待纳秒)。

    English
    --------
    Token service response (frozen slots, with enforced invariants).

    Invariants (enforced in ``__post_init__``):

    - ``DENIED``: ``token is None`` + ``deny_reason is not None``.
    - 3 grants: ``token is not None`` + ``deny_reason is None``.

    ``wait_ns`` is 0 (immediate) or > 0 (suggested wait in ns).
    """

    decision: TokenDecision
    token: Optional[Token] = None
    deny_reason: Optional[TokenDenyReason] = None
    wait_ns: int = 0
    # M6.3.2: Server 建议重试延迟 (区分 client-side vs server-side wait);
    # 默认 0 (立即), 1.0 主包 LocalTokenService 永远不填
    retry_after_ns: int = 0

    def __post_init__(self) -> None:
        if self.decision is TokenDecision.DENIED:
            if self.token is not None:
                raise ValueError("TokenResponse: DENIED requires token is None")
            if self.deny_reason is None:
                raise ValueError(
                    "TokenResponse: DENIED requires deny_reason is not None"
                )
        else:
            if self.token is None:
                raise ValueError(
                    f"TokenResponse: {self.decision.value} requires token is not None"
                )
            if self.deny_reason is not None:
                raise ValueError(
                    f"TokenResponse: {self.decision.value} requires deny_reason is None"
                )

    def is_granted(self) -> bool:
        """中文
        ----
        是否放行(覆盖 LOCAL/REMOTE/FAIL_OPEN 3 种)。

        English
        --------
        Whether granted (covers 3 grant kinds).
        """
        return self.decision in (
            TokenDecision.LOCAL_GRANTED,
            TokenDecision.REMOTE_GRANTED,
            TokenDecision.FAIL_OPEN,
        )


@runtime_checkable
class TokenService(Protocol):
    """中文
    ----
    Token 服务 Port。

    - ``acquire(resource, permits)`` 同步或协程,返回 ``TokenResponse``
    - ``release(token)`` 归还 permit;LocalTokenService 永远 no-op

    English
    --------
    Token service Port.

    - ``acquire(resource, permits)`` sync or coroutine; returns
      ``TokenResponse``.
    - ``release(token)`` returns the permit; ``LocalTokenService``
      no-ops."""

    def acquire(
        self, resource: str, permits: float
    ) -> "TokenResponse | Awaitable[TokenResponse]":
        ...

    def release(
        self, token: Token
    ) -> "None | Awaitable[None]":
        ...


@dataclass(slots=True)
class LocalTokenService:
    """中文
    ----
    本地默认 TokenService(1.0 主包默认,零 3rd-party)。

    行为:``acquire()`` 永远返回 ``LOCAL_GRANTED`` + 新 ``Token``;
    ``release()`` no-op。单进程不需要 token 协调;Cluster M6+ 替换
    成通过选定 Cluster 传输实现的 ``RemoteTokenService``。

    English
    --------
    Local default TokenService (1.0 main wheel default, zero 3rd-party).

    Behavior: ``acquire()`` always returns ``LOCAL_GRANTED`` + new
    ``Token``; ``release()`` no-op. Single-process doesn't need
    token coordination; Cluster M6+ replaces with
    ``RemoteTokenService`` over the selected Cluster transport.
    """

    def acquire(self, resource: str, permits: float) -> TokenResponse:
        """中文
        ----
        永远 LOCAL_GRANTED。

        English
        --------
        Always ``LOCAL_GRANTED``.
        """
        import time
        now_ns = time.time_ns()
        return TokenResponse(
            decision=TokenDecision.LOCAL_GRANTED,
            token=Token(
                resource=resource,
                permits=permits,
                issued_at_ns=now_ns,
                ttl_ns=0,  # permanent
            ),
            deny_reason=None,
            wait_ns=0,
        )

    def release(self, token: Token) -> None:
        """中文
        ----
        No-op(本地不需要归还)。

        English
        --------
        No-op (no local state to return).
        """
        return None


__all__ = [
    "TokenDecision",
    "TokenDenyReason",
    "ClusterFailurePolicy",  # M6.3.6
    "Token",
    "TokenResponse",
    "TokenService",
    "LocalTokenService",
]
