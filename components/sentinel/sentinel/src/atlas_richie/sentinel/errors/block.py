"""Sentinel Engine / Slot 拒绝异常(M1.1 引入)。

中文
----
``SentinelBlockedError`` 是 Engine 拒绝路径的异常根,**独立分支**于
``ResilienceError``(M0.5-A 锁定,不复用原语异常):

- ``except SentinelBlockedError`` 捕获 Engine / Slot 拒绝
- ``except CircuitOpen`` / ``except BulkheadFull`` 捕获原语直接 throw

两条 ``except`` 互不干扰。

``CircuitBlocked`` **不**继承 ``CircuitOpen``(单继承不复用原语异常);
它复制 ``retry_after`` / ``state`` / ``rule`` 等可观察字段供用户决策,
但保持类型独立。

English
--------
Sentinel Engine / Slot rejection exceptions (M1.1).

``SentinelBlockedError`` is the root of the Engine-rejection tree,
**on a separate branch** from ``ResilienceError`` (M0.5-A lock-in;
primitive exceptions are not reused):

- ``except SentinelBlockedError`` catches Engine / Slot rejections.
- ``except CircuitOpen`` / ``except BulkheadFull`` catches primitive
  throws.

The two ``except`` arms do not interfere.

``CircuitBlocked`` does **not** inherit ``CircuitOpen`` (single
inheritance, no primitive-exception reuse); it copies observable
fields (``retry_after`` / ``state`` / ``rule``) for user decisions,
but stays type-independent."""

from __future__ import annotations

from dataclasses import dataclass

from ..model.enums import BlockReason
from ..model.resource import Resource
from .base import SentinelError


class SentinelBlockedError(SentinelError):
    """中文
    ----
    Engine / Slot 拒绝异常的根。继承 ``SentinelError``,**不**继承
    ``ResilienceError``(M0.5-A 锁定;两条 except 分支互不干扰)。

    所有子类必须实现:

    - ``block_reason`` — ``BlockReason`` 枚举值(用于 metrics / 审计)
    - ``resource`` — 受保护资源
    - ``stable_code`` — 稳定字符串 code(用于跨进程 / 跨语言日志关联)
    - ``rule_id`` — 命中的规则 id(可选;SystemRule 等无规则 id 时为空)

    English
    --------
    Root of the Engine / Slot rejection tree. Inherits
    ``SentinelError``, **not** ``ResilienceError`` (M0.5-A lock-in;
    the two ``except`` arms do not interfere).

    All subclasses must implement:

    - ``block_reason`` — ``BlockReason`` enum (for metrics / audit).
    - ``resource`` — protected resource.
    - ``stable_code`` — stable string code (for cross-process /
      cross-language log correlation).
    - ``rule_id`` — matched rule id (optional; empty for SystemRule
      and similar global rules).
    """

    block_reason: BlockReason
    resource: Resource
    stable_code: str
    rule_id: str = ""

    def __init__(
        self,
        message: str,
        *,
        block_reason: BlockReason,
        resource: Resource,
        stable_code: str,
        rule_id: str = "",
    ) -> None:
        super().__init__(message)
        self.block_reason = block_reason
        self.resource = resource
        self.stable_code = stable_code
        self.rule_id = rule_id


@dataclass(frozen=True, slots=True)
class _BlockedErrorMeta:
    """中文
    ----
    内部 mixin 元信息(frozen slots dataclass,避免每个子类的 __init__ 重复)。

    English
    --------
    Internal mixin meta (frozen slots dataclass; avoids per-subclass
    __init__ boilerplate).
    """

    default_retry_after: float = 0.0


# Per-subclass retry_after / stable_code defaults; centralized so
# subclasses don't drift.
_META_FLOW = _BlockedErrorMeta(default_retry_after=0.0)
_META_PARAM_FLOW = _BlockedErrorMeta(default_retry_after=0.0)
_META_SYSTEM = _BlockedErrorMeta(default_retry_after=0.0)
_META_DEGRADE_CIRCUIT = _BlockedErrorMeta(default_retry_after=1.0)
_META_AUTHORITY = _BlockedErrorMeta(default_retry_after=0.0)
_META_BULKHEAD = _BlockedErrorMeta(default_retry_after=0.0)


class FlowBlocked(SentinelBlockedError):
    """中文
    ----
    FlowRule 拒绝(QPS / 并发 / 等待超时)。

    English
    --------
    FlowRule rejection (QPS / concurrency / wait timeout).
    """

    def __init__(
        self,
        message: str,
        *,
        resource: Resource,
        rule_id: str = "",
        retry_after: float = _META_FLOW.default_retry_after,
    ) -> None:
        super().__init__(
            message,
            block_reason=BlockReason.FLOW,
            resource=resource,
            stable_code="SENTINEL_BLOCKED_FLOW",
            rule_id=rule_id,
        )
        self.retry_after = retry_after


class ParamFlowBlocked(SentinelBlockedError):
    """中文
    ----
    ParamFlowRule 拒绝(热点参数限流)。

    English
    --------
    ParamFlowRule rejection (hot-spot parameter limit).
    """

    def __init__(
        self,
        message: str,
        *,
        resource: Resource,
        rule_id: str = "",
        retry_after: float = _META_PARAM_FLOW.default_retry_after,
    ) -> None:
        super().__init__(
            message,
            block_reason=BlockReason.PARAM_FLOW,
            resource=resource,
            stable_code="SENTINEL_BLOCKED_PARAM_FLOW",
            rule_id=rule_id,
        )
        self.retry_after = retry_after


class SystemBlocked(SentinelBlockedError):
    """中文
    ----
    SystemRule 拒绝(CPU / load / QPS / in-flight 超阈值)。

    English
    --------
    SystemRule rejection (CPU / load / QPS / in-flight over threshold).
    """

    def __init__(
        self,
        message: str,
        *,
        resource: Resource,
        retry_after: float = _META_SYSTEM.default_retry_after,
    ) -> None:
        super().__init__(
            message,
            block_reason=BlockReason.SYSTEM,
            resource=resource,
            stable_code="SENTINEL_BLOCKED_SYSTEM",
            rule_id="",
        )
        self.retry_after = retry_after


class CircuitBlocked(SentinelBlockedError):
    """中文
    ----
    DegradeSlot 因熔断器 OPEN 拒绝。

    **不**继承 ``CircuitOpen``(单继承不复用原语异常)。复制
    ``retry_after`` / ``state`` / ``rule`` 三个可观察字段供用户决策,
    类型保持独立 — 这样 ``except CircuitOpen`` 不会误捕获
    DegradeSlot 拒绝,``except SentinelBlockedError`` 也不会误捕获
    原语直接 throw。

    ``rule`` 是字符串形式(``"closed"`` / ``"open"`` / ``"half_open"``),
    而不是枚举 — 序列化跨进程日志时不依赖特定 enum 定义。

    English
    --------
    DegradeSlot rejection because the circuit breaker is OPEN.

    Does **not** inherit ``CircuitOpen`` (single inheritance, no
    primitive-exception reuse). Copies the ``retry_after`` / ``state``
    / ``rule`` observable fields for user decisions, but stays
    type-independent — so ``except CircuitOpen`` does not catch
    DegradeSlot rejections, and ``except SentinelBlockedError`` does
    not catch primitive throws.

    ``state`` is a string (``"closed"`` / ``"open"`` / ``"half_open"``)
    rather than an enum, so cross-process log serialization doesn't
    depend on a specific enum definition.
    """

    def __init__(
        self,
        message: str,
        *,
        resource: Resource,
        retry_after: float,
        state: str,
        rule_id: str = "",
    ) -> None:
        if state not in ("closed", "open", "half_open"):
            raise ValueError(
                f"CircuitBlocked.state must be one of "
                f"'closed'/'open'/'half_open', got {state!r}"
            )
        super().__init__(
            message,
            block_reason=BlockReason.CIRCUIT_OPEN,
            resource=resource,
            stable_code="SENTINEL_BLOCKED_CIRCUIT",
            rule_id=rule_id,
        )
        self.retry_after = retry_after
        self.state = state
        # alias for callers that prefer `rule` (matches DegradeRule field name)
        self.rule = rule_id


class AuthorityDenied(SentinelBlockedError):
    """中文
    ----
    AuthorityRule 拒绝(黑白名单 / 可信 origin 失败)。

    English
    --------
    AuthorityRule rejection (deny list / trusted origin failure).
    """

    def __init__(
        self,
        message: str,
        *,
        resource: Resource,
        rule_id: str = "",
        origin: str = "",
        retry_after: float = _META_AUTHORITY.default_retry_after,
    ) -> None:
        super().__init__(
            message,
            block_reason=BlockReason.AUTHORITY,
            resource=resource,
            stable_code="SENTINEL_BLOCKED_AUTHORITY",
            rule_id=rule_id,
        )
        self.retry_after = retry_after
        self.origin = origin


__all__ = [
    "SentinelBlockedError",
    "FlowBlocked",
    "ParamFlowBlocked",
    "SystemBlocked",
    "CircuitBlocked",
    "AuthorityDenied",
]
