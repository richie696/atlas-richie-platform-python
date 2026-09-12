"""Sentinel FlowSlot(M2.1)。

中文
----
``FlowSlot`` 实现 4 种 ``FlowScope`` 的计数 + 限流;对每个命中的
``FlowRule`` 走一次判定,任一拒绝即抛 ``FlowBlocked``。

设计要点:

- **per-rule SlidingWindow**:每个 rule_id 单独维护一个 SlidingWindow
  (key 包含 scope + scope_reference 时,key 拼对应维度)
- **CONCURRENCY 用 counter + 锁**:不进 SlidingWindow,而是 ``int`` 累加
  (entry 时 +1,exit 时 -1);Engine SlotChain 的 lease.release_all
  顺序保证计数最后归还
- **QUEUE / WARM_UP 占位**:M2.1 实现 REJECT(默认);QUEUE / WARM_UP
  留给 M2.x 优化版
- **scope 分桶**:DIRECT 用 rule_id;ORIGIN/ASSOCIATED_RESOURCE/CALL_PATH
  用 ``(rule_id, scope_reference)`` 拼 key

English
--------
Sentinel FlowSlot (M2.1).

``FlowSlot`` implements counting + limiting for the 4 ``FlowScope``s;
each matching ``FlowRule`` is evaluated; any rejection raises
``FlowBlocked``.

Design points:

- **per-rule SlidingWindow** — each rule_id owns its own SlidingWindow
  (key includes scope + scope_reference when applicable).
- **CONCURRENCY uses counter + lock** — not a SlidingWindow; uses
  ``int`` accumulator (+1 on entry, -1 on exit). Engine's
  SlotChain lease.release_all order guarantees the counter is reset
  last.
- **QUEUE / WARM_UP placeholder** — M2.1 implements REJECT (default);
  QUEUE / WARM_UP deferred to M2.x.
- **Scope bucketing** — DIRECT uses rule_id; ORIGIN / ASSOCIATED_RESOURCE
  / CALL_PATH use ``(rule_id, scope_reference)`` composite key."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..engine.slot import ORDER_FLOW, Slot
from ..errors import FlowBlocked
from ..metrics.sliding_window import SlidingWindow
from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.outcome import Outcome
from ..model.resource import Resource
from ..primitives.clock import Clock, SystemClock
from ..rules.flow import FlowGrade, FlowRule, FlowScope


@dataclass(slots=True)
class _RuleCounters:
    """中文
    ----
    每个 rule 的 QPS SlidingWindow + CONCURRENCY 计数。

    CONCURRENCY counter 不进 SlidingWindow,直接在 ``_concurrency``;
    QPS 走 ``_window``。两套共享 entry 路径,但 lease 互不影响
    (QPS 计数不入 lease,CONCURRENCY 计数靠 lease 释放归还)。

    English
    --------
    Per-rule QPS SlidingWindow + CONCURRENCY counter.

    CONCURRENCY counter doesn't use SlidingWindow; ``_concurrency`` is
    a plain int. QPS goes through ``_window``. Both share the entry
    path, but leases are independent (QPS doesn't enter lease;
    CONCURRENCY relies on lease release to decrement).
    """

    _window: SlidingWindow
    _concurrency: int = 0


class FlowSlot(Slot):
    """中文
    ----
    FlowRule 限流 Slot。

    用法::

        engine.add_slot(FlowSlot(rules_index=repo.current_index))

    ``rules_index`` 接受一个 callable(``RuleIndex | None``)或直接
    ``RuleIndex``;Engine 在每次 entry 时调 ``rules_index()`` 取最新
    index(支持 RuleRepository 原子 swap 后立即生效)。

    English
    --------
    FlowRule limiting slot.

    Usage::

        engine.add_slot(FlowSlot(rules_index=repo.current_index))

    ``rules_index`` accepts a callable (``RuleIndex | None``) or a
    direct ``RuleIndex``; Engine calls ``rules_index()`` on each
    entry to get the latest index (so atomic swap takes effect
    immediately).
    """

    @property
    def order(self) -> int:
        return ORDER_FLOW

    def __init__(
        self,
        *,
        rules_index: Any = None,
        clock: Clock | None = None,
        bucket_ms: int = 500,
        bucket_count: int = 10,
    ) -> None:
        # rules_index may be a RuleIndex, a callable, or None
        self._rules_index = rules_index
        self._clock = clock or SystemClock()
        self._bucket_ms = bucket_ms
        self._bucket_count = bucket_count
        # Per-rule counters, keyed by (rule_id, scope_reference) or just rule_id
        self._counters: dict[tuple, _RuleCounters] = {}
        # Per-entry acquired (rule_id, counter) for release on exit
        # entry_id -> list of (rule_id, is_concurrency)
        self._acquired: dict[int, list[tuple[str, bool]]] = defaultdict(list)
        self._entry_seq = 0

    def _get_counters(self, rule: FlowRule) -> _RuleCounters:
        if rule.scope is FlowScope.DIRECT:
            key = (rule.rule_id,)
        else:
            key = (rule.rule_id, rule.scope_reference or "")
        counter = self._counters.get(key)
        if counter is None:
            counter = _RuleCounters(
                _window=SlidingWindow(
                    clock=self._clock,
                    bucket_ms=self._bucket_ms,
                    bucket_count=self._bucket_count,
                )
            )
            self._counters[key] = counter
        return counter

    def _now_ms(self) -> int:
        return int(self._clock.now() * 1000)

    def _resolve_rules(self, resource: Resource) -> list[FlowRule]:
        """中文
        ----
        解析出本 entry 命中的 FlowRule 列表(按 Index 优先级)。

        ``rules_index`` 是 RuleIndex 实例时直接查;是 callable 时调它
        取最新;是 None 时返回空列表(slot 不工作)。

        English
        --------
        Resolve the FlowRule list for this entry (Index priority order).

        If ``rules_index`` is a RuleIndex, query directly; if callable,
        call to get latest; if None, return empty (slot no-op).
        """
        if self._rules_index is None:
            return []
        idx = (
            self._rules_index()
            if callable(self._rules_index)
            else self._rules_index
        )
        if idx is None:
            return []
        matched = []
        seen: set[str] = set()
        for indexed in idx.find(resource.name):
            rule = indexed.rule
            if not isinstance(rule, FlowRule):
                continue
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            matched.append(rule)
        return matched

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        rules = self._resolve_rules(resource)
        if not rules:
            return _NoopFlowLease()
        self._entry_seq += 1
        entry_id = self._entry_seq
        acquired: list[tuple[str, bool]] = []
        for rule in rules:
            counter = self._get_counters(rule)
            if rule.grade is FlowGrade.QPS:
                passed, _blocked = counter._window.sum(self._now_ms())
                if passed >= rule.threshold:
                    # 取消之前已 acquired 的计数
                    for rid, is_conc in acquired:
                        if is_conc:
                            c = self._counters.get(
                                (rid,) if rid not in (
                                    r.rule_id for r in rules if r.scope is not FlowScope.DIRECT
                                ) else (rid, "")
                            )
                            if c is not None:
                                c._concurrency = max(0, c._concurrency - 1)
                    raise FlowBlocked(
                        f"FlowRule {rule.rule_id!r}: QPS {passed:.0f} >= {rule.threshold:.0f}",
                        resource=resource,
                        rule_id=rule.rule_id,
                        retry_after=1.0,
                    )
                counter._window.record_pass(self._now_ms())
                acquired.append((rule.rule_id, False))
            elif rule.grade is FlowGrade.CONCURRENCY:
                if counter._concurrency >= rule.threshold:
                    for rid, is_conc in acquired:
                        if is_conc:
                            c = self._counters.get((rid,))
                            if c is not None:
                                c._concurrency = max(0, c._concurrency - 1)
                    raise FlowBlocked(
                        f"FlowRule {rule.rule_id!r}: concurrency {counter._concurrency:.0f} >= {rule.threshold:.0f}",
                        resource=resource,
                        rule_id=rule.rule_id,
                        retry_after=0.0,
                    )
                counter._concurrency += 1
                acquired.append((rule.rule_id, True))
        self._acquired[entry_id] = acquired
        return _FlowLease(slot=self, entry_id=entry_id)

    def on_entry_complete(self, outcome: Outcome) -> None:
        # 入口统计 metric(简化:不重置 _acquired,_FlowLease.release 负责)
        pass

    def _release(self, entry_id: int) -> None:
        acquired = self._acquired.pop(entry_id, [])
        for rule_id, is_conc in acquired:
            if is_conc:
                # 找对应的 counter
                for key, c in self._counters.items():
                    if key[0] == rule_id:
                        c._concurrency = max(0, c._concurrency - 1)
                        break


@dataclass(slots=True)
class _NoopFlowLease:
    """中文
    ----
    当 Slot 没匹配到任何 FlowRule 时,Engine 拿到的 Noop Lease。

    English
    --------
    Noop Lease returned when no FlowRule matched.
    """

    async def release(self) -> None:
        return None


@dataclass(slots=True)
class _FlowLease:
    """中文
    ----
    FlowSlot 发放的 lease;``release()`` 时归还所有 acquired 的
    CONCURRENCY 计数(QPS 计数已经在 SlidingWindow 内,无需归还)。

    English
    --------
    FlowSlot's lease; ``release()`` returns all acquired CONCURRENCY
    counters (QPS counters live in the SlidingWindow and don't need
    return)."""

    slot: FlowSlot
    entry_id: int

    async def release(self) -> None:
        self.slot._release(self.entry_id)


__all__ = ["FlowSlot", "_FlowLease", "_NoopFlowLease"]
