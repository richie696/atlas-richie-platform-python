"""Sentinel SystemSlot(M2.4)。

中文
----
``SystemSlot`` 是 Engine 入口级 Slot,基于 ``SystemMetricSampler``
采样 + ``SystemRule`` 阈值判定。DIRECT 模式任一阈值超即抛
``SystemBlocked``;ADAPTIVE_CAPACITY 模式用 Little's Law 估算可承
受量。

设计要点:

- **只对 INBOUND 资源生效**;``INTERNAL`` / ``OUTBOUND`` 直接
  no-op 跳过(PLANNING §M2.4 Exit Criteria)
- **Order=400** 在 Authority 之后、Flow 之前(让 Authority 先做
  黑白名单 / 可信 origin,挡住无权限请求)
- **sampler degraded fail-safe**:sampler 报告 ``degraded=True`` 时
  SystemSlot 跳过本规则,记录 ``last_error``,**不**触发 SystemBlocked
- **ADAPTIVE_CAPACITY** 公式:``estimated_capacity = max(1,
  completed_qps * min_stable_rt_ms / 1000)``;若 ``in_flight_qps >=
  estimated_capacity`` → 拒绝

English
--------
Sentinel SystemSlot (M2.4).

``SystemSlot`` is Engine entry-level; uses ``SystemMetricSampler`` to
sample + ``SystemRule`` to threshold. DIRECT: any hard threshold
triggers ``SystemBlocked``; ADAPTIVE_CAPACITY: Little's Law
estimation.

Design points:

- **Only INBOUND resources** — ``INTERNAL`` / ``OUTBOUND`` no-op
  skip (PLANNING §M2.4 Exit Criteria).
- **Order=400** after Authority, before Flow (so Authority short-
  circuits unauthorized requests first).
- **sampler degraded fail-safe** — sampler reports ``degraded=True``
  → SystemSlot skips this rule + records ``last_error``; **does
  not** trigger SystemBlocked.
- **ADAPTIVE_CAPACITY** formula: ``estimated_capacity = max(1,
  completed_qps * min_stable_rt_ms / 1000)``; if
  ``in_flight_qps >= estimated_capacity`` → reject."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from ..engine.slot import ORDER_SYSTEM, Slot
from ..errors import SystemBlocked
from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.resource import Resource, ResourceKind, TrafficType
from ..ports.system_metric_sampler import (
    DefaultSystemMetricSampler,
    SystemMetricSampler,
    SystemSnapshot,
)
from ..rules.system import SystemRule, SystemStrategy


class SystemSlot(Slot):
    """中文
    ----
    进程级自适应保护 Slot。

    用法::

        sampler = DefaultSystemMetricSampler()
        engine.add_slot(SystemSlot(rules_index=..., sampler=sampler))
        # Engine 在 _run_slot_chain_enter 时调 sampler.record_enter(),
        # 在 _finalize_entry 时调 sampler.record_complete(success=...)

    English
    --------
    Process-level adaptive protection slot.

    Usage::

        sampler = DefaultSystemMetricSampler()
        engine.add_slot(SystemSlot(rules_index=..., sampler=sampler))
        # Engine calls sampler.record_enter() during
        # _run_slot_chain_enter, and sampler.record_complete() in
        # _finalize_entry.
    """

    @property
    def order(self) -> int:
        return ORDER_SYSTEM

    def __init__(
        self,
        *,
        rules_index: Any = None,
        system_rules: list[SystemRule] | None = None,
        sampler: SystemMetricSampler | None = None,
    ) -> None:
        # SystemRule 没有 selector (ADR-SEN-015),不接受 RuleIndex;
        # 直接接 list[SystemRule] (按 priority 排序,调用方负责)
        self._rules_index = rules_index
        self._system_rules = sorted(
            system_rules or [], key=lambda r: -r.priority
        )
        self._sampler = sampler or DefaultSystemMetricSampler()
        self._last_error: BaseException | None = None
        self._last_snapshot: SystemSnapshot | None = None

    def set_system_rules(self, rules: list[SystemRule]) -> None:
        """中文
        ----
        替换 system rules 列表(Adapter 注入或 Repository 推送)。

        English
        --------
        Replace system rules list (Adapter injection or Repository
        push).
        """
        self._system_rules = sorted(rules, key=lambda r: -r.priority)

    @property
    def last_error(self) -> BaseException | None:
        return self._last_error

    @property
    def last_snapshot(self) -> SystemSnapshot | None:
        return self._last_snapshot

    def _resolve_rules(self, resource: Resource) -> list[SystemRule]:
        # SystemRule 不走 RuleIndex,直接用 system_rules 列表
        return list(self._system_rules)

    def _sample(self) -> SystemSnapshot:
        sample = self._sampler.sample()
        # Handle async sampler (Protocol allows coroutine return)
        if asyncio.iscoroutine(sample):
            # M2.4 占位: 同步 + 协程 sampler 都支持; 协程需要 await
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 已在 event loop 内, 协程 sampler 需要 Engine 改 await
                    # 这里 M2.4 占位返回 degraded
                    self._last_snapshot = SystemSnapshot(
                        cpu_usage=None, load=None,
                        event_loop_lag_ms=None,
                        in_flight_qps=None, completed_qps=None,
                        at_ns=0, degraded=True,
                    )
                    return self._last_snapshot
                sample = loop.run_until_complete(sample)  # type: ignore[arg-type]
            except RuntimeError:
                sample = SystemSnapshot(
                    cpu_usage=None, load=None,
                    event_loop_lag_ms=None,
                    in_flight_qps=None, completed_qps=None,
                    at_ns=0, degraded=True,
                )
        self._last_snapshot = sample
        return sample

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        # 只对 INBOUND 资源生效
        if resource.traffic_type is not TrafficType.INBOUND:
            return _NoopSystemLease()
        rules = self._resolve_rules(resource)
        if not rules:
            return _NoopSystemLease()
        snap = self._sample()
        if snap.degraded:
            # sampler 失败, 跳过规则检查, 记录 last_error
            try:
                raise RuntimeError(
                    "SystemMetricSampler degraded; "
                    f"snapshot={snap}"
                )
            except RuntimeError as e:
                self._last_error = e
            return _NoopSystemLease()
        for rule in rules:
            self._check_rule(rule, resource, snap)
        return _NoopSystemLease()

    def _check_rule(
        self, rule: SystemRule, resource: Resource, snap: SystemSnapshot
    ) -> None:
        if rule.strategy is SystemStrategy.DIRECT:
            self._check_direct(rule, resource, snap)
        else:
            self._check_adaptive(rule, resource, snap)

    def _check_direct(
        self, rule: SystemRule, resource: Resource, snap: SystemSnapshot
    ) -> None:
        reasons: list[str] = []
        if (
            rule.max_cpu_usage is not None
            and snap.cpu_usage is not None
            and snap.cpu_usage > rule.max_cpu_usage
        ):
            reasons.append(f"cpu={snap.cpu_usage:.2f} > {rule.max_cpu_usage:.2f}")
        if (
            rule.max_load is not None
            and snap.load is not None
            and snap.load > rule.max_load
        ):
            reasons.append(f"load={snap.load:.2f} > {rule.max_load:.2f}")
        if (
            rule.max_event_loop_lag_ms is not None
            and snap.event_loop_lag_ms is not None
            and snap.event_loop_lag_ms > rule.max_event_loop_lag_ms
        ):
            reasons.append(
                f"event_loop_lag={snap.event_loop_lag_ms:.1f}ms > "
                f"{rule.max_event_loop_lag_ms:.1f}ms"
            )
        if (
            rule.max_in_flight_qps is not None
            and snap.in_flight_qps is not None
            and snap.in_flight_qps > rule.max_in_flight_qps
        ):
            reasons.append(
                f"in_flight_qps={snap.in_flight_qps:.0f} > "
                f"{rule.max_in_flight_qps:.0f}"
            )
        if reasons:
            raise SystemBlocked(
                f"SystemRule {rule.rule_id!r}: " + "; ".join(reasons),
                resource=resource,
                retry_after=1.0,
            )

    def _check_adaptive(
        self, rule: SystemRule, resource: Resource, snap: SystemSnapshot
    ) -> None:
        if snap.completed_qps is None or snap.in_flight_qps is None:
            return
        # estimated_capacity = max(1, completed_qps * min_stable_rt_ms / 1000)
        estimated = max(
            1.0,
            snap.completed_qps * rule.min_stable_rt_ms / 1000.0,
        )
        estimated = min(estimated, float(rule.max_concurrent_adaptive))
        if snap.in_flight_qps >= estimated:
            raise SystemBlocked(
                f"SystemRule {rule.rule_id!r}: adaptive capacity "
                f"in_flight={snap.in_flight_qps:.0f} >= "
                f"estimated={estimated:.0f}",
                resource=resource,
                retry_after=1.0,
            )


@dataclass(slots=True)
class _NoopSystemLease:
    async def release(self) -> None:
        return None


__all__ = ["SystemSlot", "_NoopSystemLease"]
