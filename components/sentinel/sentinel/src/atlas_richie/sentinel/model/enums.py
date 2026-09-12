"""Sentinel 领域枚举(BlockReason / RuleMatchKind / EngineState)。

中文
----
三个跨 Slot / 跨规则共享的枚举,集中放在 `model/enums.py` 而非分到
`rules/` 或 `engine/`,因为它们是**领域语义**而不是具体实现细节。

English
--------
Three cross-Slot, cross-rule enums grouped here (not in ``rules/`` or
``engine/``) because they encode **domain semantics** rather than
implementation details."""

from __future__ import annotations

from enum import StrEnum


class BlockReason(StrEnum):
    """中文
    ----
    拒绝原因(出现在 ``SentinelBlockedError.block_reason`` 和 metrics 中)。

    - FLOW — FlowRule 命中(QPS / 并发 / 等待超时)
    - PARAM_FLOW — ParamFlowRule 命中(热点参数限流)
    - SYSTEM — SystemRule 命中(CPU/load/QPS/in-flight)
    - DEGRADE — DegradeRule 命中(降级开关 / 异常计数)
    - AUTHORITY — AuthorityRule 命中(黑白名单 / 可信 origin 失败)
    - POOL_FULL — PoolGuard 出站池满
    - CIRCUIT_OPEN — 熔断器 OPEN(注:仅在 Engine / DegradeSlot 拒绝时使用;
      原语直接 throw 的 `CircuitOpen` 异常不在此列)

    English
    --------
    Rejection reason (present in ``SentinelBlockedError.block_reason``
    and metrics).

    Note: ``CIRCUIT_OPEN`` is only used by Engine / DegradeSlot
    rejection; primitive-thrown ``CircuitOpen`` exceptions are not
    classified here.
    """

    FLOW = "flow"
    PARAM_FLOW = "param_flow"
    SYSTEM = "system"
    DEGRADE = "degrade"
    AUTHORITY = "authority"
    POOL_FULL = "pool_full"
    CIRCUIT_OPEN = "circuit_open"


class RuleMatchKind(StrEnum):
    """中文
    ----
    规则匹配方式(决定 ``SlotChain`` 用哪种匹配策略)。

    - RESOURCE — 按 Resource.name 精确匹配
    - AUTHORITY — 按调用 origin 匹配(AuthorityRule 专属)
    - SYSTEM — SystemRule 不按 Resource 匹配,直接看进程级指标
    - PARAMETER — 按参数 key + value 匹配(ParamFlowRule)
    - ADAPTIVE — Little's Law 自适应容量计算(SystemRule ADAPTIVE 模式)

    English
    --------
    Rule matching strategy (used by ``SlotChain`` to pick the right
    matcher).
    """

    RESOURCE = "resource"
    AUTHORITY = "authority"
    SYSTEM = "system"
    PARAMETER = "parameter"
    ADAPTIVE = "adaptive"


class EngineState(StrEnum):
    """中文
    ----
    ``SentinelEngine`` 自身的 6 状态机(详见 M1.2)。

    - CREATED — 刚 ``SentinelEngine()`` 构造
    - INITIALIZING — ``async with engine:`` 进入,正在装入 rules / 启动 metric
    - READY — 可接受 ``engine.entry(...)`` 调用
    - SHUTTING_DOWN — 退出 ``async with``,等待 in-flight entry 结束
    - SHUTDOWN — 资源释放完成,不可再 ``engine.entry``
    - FAILED — 初始化或运行中出错;不可再 entry,需查 ``engine.last_error``

    非法迁移(例如 SHUTDOWN → READY)抛 ``SentinelLifecycleError``。

    English
    --------
    ``SentinelEngine`` 6-state machine (see M1.2).

    Illegal transitions (e.g. SHUTDOWN → READY) raise
    ``SentinelLifecycleError``.
    """

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    SHUTTING_DOWN = "shutting_down"
    SHUTDOWN = "shutdown"
    FAILED = "failed"


__all__ = ["BlockReason", "RuleMatchKind", "EngineState"]
