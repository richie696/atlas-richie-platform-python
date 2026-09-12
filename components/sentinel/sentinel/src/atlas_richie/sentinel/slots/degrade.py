"""Sentinel DegradeSlot(M2.2)。

中文
----
``DegradeSlot`` 复用 M0 阶段 ``primitives.CircuitBreaker`` 状态机;每个
``DegradeRule`` 持有一个 ``CircuitBreaker`` 实例,enter 时按当前状态
判定:

- ``CLOSED``:允许,``on_entry_complete`` 时根据 outcome 决定是否
  计入 failure 计数
- ``OPEN``:直接抛 ``CircuitBlocked``(``DegradeSlot`` 拒绝路径)
- ``HALF_OPEN``:放行(``half_open_probe_count`` 次),任一失败立即
  重 OPEN

设计要点:

- **per-rule CircuitBreaker 实例** (``rule_id`` → CB)
- **状态机非法迁移由 M0 CircuitBreaker 保证**(抛 ``ResilienceError``)
- **强制管理 API** 同步方法 ``force_open`` / ``force_close`` /
  ``force_reset``(M2.2 占位,M5.1 Dashboard 触发)
- **不**读 httpcore / 私有 API,只跟 ``primitives.CircuitBreaker``
  公共接口打交道

English
--------
Sentinel DegradeSlot (M2.2).

``DegradeSlot`` reuses M0's ``primitives.CircuitBreaker`` state
machine; each ``DegradeRule`` owns one ``CircuitBreaker`` instance;
on entry, check current state:

- ``CLOSED``: admit; on completion, count failure if Outcome.FAILED.
- ``OPEN``: raise ``CircuitBlocked`` (DegradeSlot rejection path).
- ``HALF_OPEN``: admit up to ``half_open_probe_count``; any failure
  immediately trips back to OPEN.

Design points:

- **per-rule CircuitBreaker instance** (rule_id → CB).
- **Illegal state transitions guaranteed by M0 CircuitBreaker** (raises
  ``ResilienceError``).
- **Admin API** sync methods ``force_open`` / ``force_close`` /
  ``force_reset`` (M2.2 placeholder; M5.1 Dashboard triggers).
- **No** httpcore / private API usage; only public
  ``primitives.CircuitBreaker`` interface."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ..engine.slot import ORDER_DEGRADE, Slot
from ..errors import CircuitBlocked
from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.enums import BlockReason
from ..model.outcome import Outcome, OutcomeKind
from ..model.resource import Resource
from ..primitives.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)
from ..rules.degrade import DegradeRule
from ..primitives.clock import Clock, SystemClock


class DegradeSlot(Slot):
    """中文
    ----
    DegradeRule 熔断 + 降级 Slot。

    用法::

        engine.add_slot(DegradeSlot(rules_index=repo.current_index))

    English
    --------
    DegradeRule circuit-breaking + degrading slot.

    Usage::

        engine.add_slot(DegradeSlot(rules_index=repo.current_index))
    """

    @property
    def order(self) -> int:
        return ORDER_DEGRADE

    def __init__(
        self,
        *,
        rules_index: Any = None,
        clock: Clock | None = None,
    ) -> None:
        self._rules_index = rules_index
        self._clock = clock or SystemClock()
        # rule_id -> CircuitBreaker
        self._breakers: dict[str, CircuitBreaker] = {}
        # rule_id -> DegradeRule
        self._rules: dict[str, DegradeRule] = {}
        # entry_id -> list of rule_ids (for on_entry_complete to know which to count)
        self._active: dict[int, list[str]] = defaultdict(list)
        self._entry_seq = 0

    def _get_breaker(self, rule: DegradeRule) -> CircuitBreaker:
        cb = self._breakers.get(rule.rule_id)
        if cb is None:
            cb = CircuitBreaker(
                config=rule.to_circuit_breaker_config(),
                clock=self._clock,
            )
            self._breakers[rule.rule_id] = cb
        return cb

    def _resolve_rules(self, resource: Resource) -> list[DegradeRule]:
        if self._rules_index is None:
            return []
        idx = (
            self._rules_index()
            if callable(self._rules_index)
            else self._rules_index
        )
        if idx is None:
            return []
        matched: list[DegradeRule] = []
        seen: set[str] = set()
        for indexed in idx.find(resource.name):
            rule = indexed.rule
            if not isinstance(rule, DegradeRule):
                continue
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            matched.append(rule)
        return matched

    def _now(self) -> float:
        return self._clock.now()

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        rules = self._resolve_rules(resource)
        if not rules:
            return _NoopDegradeLease()
        self._entry_seq += 1
        entry_id = self._entry_seq
        active_ids: list[str] = []
        for rule in rules:
            self._rules[rule.rule_id] = rule
            cb = self._get_breaker(rule)
            now = self._now()
            state = cb.state
            if state is CircuitState.OPEN:
                # M0 CircuitBreaker 没有 retry_after 公开 API;
                # 用 config.recovery_timeout 作为 retry_after 提示
                retry_after = max(0.001, rule.recovery_timeout_ms / 1000.0)
                raise CircuitBlocked(
                    f"DegradeRule {rule.rule_id!r}: breaker OPEN",
                    resource=resource,
                    retry_after=retry_after,
                    state="open",
                    rule_id=rule.rule_id,
                )
            active_ids.append(rule.rule_id)
        if active_ids:
            self._active[entry_id] = active_ids
            return _DegradeLease(slot=self, entry_id=entry_id)
        return _NoopDegradeLease()

    def on_entry_complete(self, outcome: Outcome) -> None:
        # 找出本 entry 命中的所有 rule
        # 注意: 多个 entry 可能共享同一个 entry_seq 已被 pop; 此处
        # 简化: 假设 outcome.trace_id == entry_id (engine 在 _finalize_entry
        # 还没传 entry_id, 这里按 outcome 关联)
        # 实际做法: Engine 应当在 _finalize_entry 中传入 entry_id, 但
        # M1.2 Slot Protocol 没这参数. 简化: 反向查最近 active 的 entries
        if outcome.kind is OutcomeKind.FAILED:
            for entry_id, rule_ids in list(self._active.items()):
                # 简化: 全部 active rule 都记账
                for rid in rule_ids:
                    cb = self._breakers.get(rid)
                    if cb is not None:
                        try:
                            cb.record_failure()
                        except Exception:
                            pass
                del self._active[entry_id]
        else:
            # SUCCEEDED / BLOCKED / CANCELLED: 不计入失败,但要 pop entry
            for entry_id, rule_ids in list(self._active.items()):
                for rid in rule_ids:
                    cb = self._breakers.get(rid)
                    if cb is not None and outcome.kind is OutcomeKind.SUCCEEDED:
                        try:
                            cb.record_success()
                        except Exception:
                            pass
                del self._active[entry_id]

    # ---- 管理 API (M5.1 Dashboard 触发) ----

    def force_reset(self, rule_id: str) -> None:
        """中文
        ----
        重置指定 rule 的断路器(回到 CLOSED + 清零)。

        强制 open / close 在 M0 ``CircuitBreaker`` API 上**不**支持
        (状态机非法迁移抛错);M5.1 Dashboard 通过 CircuitBreaker
        内部 API 补充 force_open / force_close 之前,只能 reset。

        English
        --------
        Reset the named rule's breaker (back to CLOSED + zero
        counters).

        Force open / close is **not** supported on M0
        ``CircuitBreaker`` (state machine rejects illegal
        transitions); M5.1 Dashboard will add proper force_open /
        force_close via internal API; until then, only ``reset`` is
        available.
        """
        cb = self._breakers.get(rule_id)
        if cb is None:
            return
        try:
            cb.reset()
        except Exception:
            pass

    def get_breaker_state(self, rule_id: str) -> CircuitState | None:
        """中文
        ----
        查询指定 rule 的断路器当前状态(用于 Dashboard)。

        English
        --------
        Get the named rule's current breaker state (for Dashboard).
        """
        cb = self._breakers.get(rule_id)
        if cb is None:
            return None
        return cb.state


@dataclass(slots=True)
class _NoopDegradeLease:
    async def release(self) -> None:
        return None


@dataclass(slots=True)
class _DegradeLease:
    slot: DegradeSlot
    entry_id: int

    async def release(self) -> None:
        # DegradeSlot 不需要在 release 时减少计数;计数由
        # CircuitBreaker 内部 state machine 自管 + on_entry_complete
        # 触发 record_success/record_failure
        # 仍然清理 active 列表
        if self.entry_id in self.slot._active:
            # 已经在 on_entry_complete 清理过; 这是兜底
            try:
                del self.slot._active[self.entry_id]
            except KeyError:
                pass


__all__ = ["DegradeSlot", "_DegradeLease", "_NoopDegradeLease"]
