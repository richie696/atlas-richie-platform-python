"""Sentinel ParamFlowSlot(M2.3)。

中文
----
``ParamFlowSlot`` 按参数 value 分桶,每个 value 一个 SlidingWindow
统计 QPS / 并发;超 ``threshold`` 抛 ``ParamFlowBlocked``。

设计要点:

- 6 种 ParameterSource 的 extract:POSITIONAL / KEYWORD 从
  ``InvocationArguments`` 拿,HEADER / QUERY / COOKIE 从
  ``SentinelContext`` 拿(由 ASGI middleware 注入,M3.x 接入),
  CUSTOM 走 ``extractor_id`` 注册表(M3.x 接入)
- 基数治理:``_per_value_windows: dict[value, (SlidingWindow,
  last_access_ms)]``;``max_distinct_values`` 超限按 ``overflow_error``
  处理(True → 抛 ``ParamFlowBlocked``,False → 退化全局 bucket)
- 闲置淘汰:idle_ttl_ms 内未访问的 value 在 entry 时 lazy 删

English
--------
Sentinel ParamFlowSlot (M2.3).

``ParamFlowSlot`` buckets by parameter value; each value has a
SlidingWindow for QPS / concurrency; over ``threshold`` raises
``ParamFlowBlocked``.

Design points:

- 6 ParameterSource extractors: POSITIONAL / KEYWORD from
  ``InvocationArguments``; HEADER / QUERY / COOKIE from
  ``SentinelContext`` (populated by ASGI middleware, M3.x wiring);
  CUSTOM via ``extractor_id`` registry (M3.x wiring).
- Cardinality governance: ``_per_value_windows: dict[value,
  (SlidingWindow, last_access_ms)]``; ``max_distinct_values`` cap
  handled per ``overflow_error`` (True → raise ``ParamFlowBlocked``;
  False → degrade to global bucket).
- Idle eviction: values untouched within ``idle_ttl_ms`` lazily
  removed on entry."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..engine.slot import ORDER_PARAM_FLOW, Slot
from ..errors import ParamFlowBlocked
from ..metrics.sliding_window import SlidingWindow
from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.resource import Resource
from ..primitives.clock import Clock, SystemClock
from ..rules.param_flow import ParameterSource, ParamFlowRule


class ParamFlowSlot(Slot):
    """中文
    ----
    热点参数限流 Slot。

    用法::

        engine.add_slot(ParamFlowSlot(rules_index=repo.current_index))

    English
    --------
    Hot-spot parameter limiting slot.

    Usage::

        engine.add_slot(ParamFlowSlot(rules_index=repo.current_index))
    """

    @property
    def order(self) -> int:
        return ORDER_PARAM_FLOW

    def __init__(
        self,
        *,
        rules_index: Any = None,
        clock: Clock | None = None,
        bucket_ms: int = 500,
        bucket_count: int = 10,
    ) -> None:
        self._rules_index = rules_index
        self._clock = clock or SystemClock()
        self._bucket_ms = bucket_ms
        self._bucket_count = bucket_count
        # rule_id -> (OrderedDict[value, _ValueState])
        self._per_rule: dict[str, _RuleState] = {}

    def _get_rule_state(self, rule: ParamFlowRule) -> _RuleState:
        rs = self._per_rule.get(rule.rule_id)
        if rs is None:
            rs = _RuleState(
                rule=rule,
                values=OrderedDict(),
                global_window=SlidingWindow(
                    clock=self._clock,
                    bucket_ms=self._bucket_ms,
                    bucket_count=self._bucket_count,
                ),
            )
            self._per_rule[rule.rule_id] = rs
        return rs

    def _now_ms(self) -> int:
        return int(self._clock.now() * 1000)

    def _resolve_rules(self, resource: Resource) -> list[ParamFlowRule]:
        if self._rules_index is None:
            return []
        idx = (
            self._rules_index()
            if callable(self._rules_index)
            else self._rules_index
        )
        if idx is None:
            return []
        matched: list[ParamFlowRule] = []
        seen: set[str] = set()
        for indexed in idx.find(resource.name):
            rule = indexed.rule
            if not isinstance(rule, ParamFlowRule):
                continue
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            matched.append(rule)
        return matched

    def _extract_value(
        self, rule: ParamFlowRule, args: InvocationArguments | None, context: SentinelContext
    ) -> str | None:
        """中文
        ----
        按 rule.source 提取参数 value;找不到返回 None(Slot 走"no-op"
        路径, 不拒绝)。

        HEADER / QUERY / COOKIE 从 ``context.extra`` 读(由 ASGI
        middleware 注入);M3.x 接入。

        English
        --------
        Extract parameter value per ``rule.source``; returns ``None``
        if not found (Slot takes the "no-op" path, no rejection).

        HEADER / QUERY / COOKIE read from ``context.extra`` (populated
        by ASGI middleware; M3.x wires).
        """
        if args is None:
            args = InvocationArguments()
        if rule.source is ParameterSource.POSITIONAL:
            if 0 <= rule.arg_index < len(args.positional):
                return str(args.positional[rule.arg_index])
            return None
        if rule.source is ParameterSource.KEYWORD:
            v = args.get(rule.arg_key)
            return str(v) if v is not None else None
        if rule.source in (ParameterSource.HEADER, ParameterSource.QUERY, ParameterSource.COOKIE):
            # context.extra 注入 (例如 context.extra["headers"] = {...})
            extra = context.extra or {}
            section = extra.get(rule.source.value) if isinstance(extra, dict) else {}
            if isinstance(section, dict):
                v = section.get(rule.arg_key)
                return str(v) if v is not None else None
            return None
        if rule.source is ParameterSource.CUSTOM:
            # M3.x 通过 extractor registry 解析;M2.3 占位返回 None
            return None
        return None

    def _evict_idle(self, rs: _RuleState, now_ms: int) -> None:
        if rs.rule.idle_ttl_ms <= 0:
            return
        threshold = now_ms - rs.rule.idle_ttl_ms
        stale = [v for v, st in rs.values.items() if st.last_access_ms < threshold]
        for v in stale:
            del rs.values[v]

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        rules = self._resolve_rules(resource)
        if not rules:
            return _NoopParamFlowLease()
        now_ms = self._now_ms()
        # 收集所有命中的 (rule, value) 一次判定
        for rule in rules:
            value = self._extract_value(rule, args, context)
            if value is None:
                continue  # skip: 参数没传就不限流
            rs = self._get_rule_state(rule)
            self._evict_idle(rs, now_ms)
            # 取得 / 创建 window
            vs = rs.values.get(value)
            if vs is None:
                if len(rs.values) >= rule.max_distinct_values:
                    if rule.overflow_error:
                        raise ParamFlowBlocked(
                            f"ParamFlowRule {rule.rule_id!r}: "
                            f"distinct values exceed {rule.max_distinct_values}",
                            resource=resource,
                            rule_id=rule.rule_id,
                            retry_after=1.0,
                        )
                    # 退化:用全局 bucket
                    window = rs.global_window
                else:
                    window = SlidingWindow(
                        clock=self._clock,
                        bucket_ms=self._bucket_ms,
                        bucket_count=self._bucket_count,
                    )
                    vs = _ValueState(window=window, last_access_ms=now_ms)
                    rs.values[value] = vs
            else:
                window = vs.window
                vs.last_access_ms = now_ms
            passed, _ = window.sum(now_ms)
            if passed >= rule.threshold:
                raise ParamFlowBlocked(
                    f"ParamFlowRule {rule.rule_id!r}: param {value!r} QPS "
                    f"{passed:.0f} >= {rule.threshold:.0f}",
                    resource=resource,
                    rule_id=rule.rule_id,
                    retry_after=1.0,
                )
            window.record_pass(now_ms)
        return _NoopParamFlowLease()  # 限流 slot 不需要 release


@dataclass(slots=True)
class _ValueState:
    window: SlidingWindow
    last_access_ms: int


@dataclass(slots=True)
class _RuleState:
    rule: ParamFlowRule
    values: OrderedDict[str, _ValueState] = field(default_factory=OrderedDict)
    global_window: SlidingWindow = field(default=None)  # type: ignore[assignment]


@dataclass(slots=True)
class _NoopParamFlowLease:
    async def release(self) -> None:
        return None


__all__ = ["ParamFlowSlot", "_ValueState", "_RuleState", "_NoopParamFlowLease"]
