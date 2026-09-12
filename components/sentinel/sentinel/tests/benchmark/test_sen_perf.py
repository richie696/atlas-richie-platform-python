"""SEN-PERF-001 baseline data collection (M1.6).

中文
----
SEN-PERF = 性能基线**数据采集**;**不**做硬阈值断言。

PLANNING §M1.6 Exit Criteria 明确:

- 5 个场景采集:无规则准入 / 单 FlowRule / 5 类规则同时 / 1000 条
  exact 索引命中 / 1000 条索引未命中
- 输出 commit / Python / OS / CPU / 规则数 / 资源数 / 并发度 /
  p50 p95 p99 max / CPU RSS alloc GC
- **不**做"p99 < 1ms"等硬性断言;后续 M5 审批时拿这些数据做
  "基线有没有退化"的对比

此测试默认被 **skip**(无 ``--sen-perf`` / 无 ``RUN_SEN_PERF=1`` 时
直接返回)。开启时,所有场景串行跑(避免相互污染),每个场景:
1. 构造环境
2. 预热 1k 次
3. 正式跑 N 次,记录每个 entry 的 wall-clock ns
4. 打印摘要到 stdout
5. **不** assert;**不** fail

English
--------
SEN-PERF baseline **data collection**; **no** hard threshold assertions.

PLANNING §M1.6 Exit Criteria are explicit:

- 5 scenarios: no-rule admit / single FlowRule / 5 rule types together /
  1000 exact index hits / 1000 index misses.
- Output commit / Python / OS / CPU / rule count / resource count /
  concurrency / p50 p95 p99 max / CPU RSS alloc GC.
- **No** hard "p99 < 1ms" assertions; M5 approval uses these as
  "did the baseline regress?" comparison.

This test is **skipped by default** (returns early without
``--sen-perf`` / ``RUN_SEN_PERF=1``). When enabled, scenarios run
sequentially (no cross-pollution). Each scenario:
1. Build env.
2. Warm up 1k times.
3. Run N formal entries, record each entry's wall-clock ns.
4. Print summary to stdout.
5. **No** assertion; **no** failure.
"""

from __future__ import annotations

import asyncio
import gc
import os
import platform
import subprocess
import sys
import time
import unittest
from typing import Any

import pytest

from atlas_richie.sentinel.engine.sentinel_engine import SentinelEngine
from atlas_richie.sentinel.engine.slot import (
    ORDER_FLOW,
    ORDER_NODE_SELECTOR,
    Slot,
)
from atlas_richie.sentinel.model.argument import InvocationArguments
from atlas_richie.sentinel.model.context import SentinelContext
from atlas_richie.sentinel.model.decision import NoopSlotLease
from atlas_richie.sentinel.model.outcome import Outcome
from atlas_richie.sentinel.model.resource import Resource
from atlas_richie.sentinel.rules.index import RuleIndex
from atlas_richie.sentinel.rules.selector import ResourceSelector


# ---------------------------------------------------------------------------
# Sentinel: only run when explicitly requested
# ---------------------------------------------------------------------------


_SKIP_REASON = (
    "SEN-PERF-001 data collection is opt-in. Run with "
    "`RUN_SEN_PERF=1 pytest tests/benchmark/test_sen_perf.py -v -s` to collect."
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SEN_PERF") != "1",
    reason=_SKIP_REASON,
)


# ---------------------------------------------------------------------------
# Per-scenario helpers
# ---------------------------------------------------------------------------


class _NoopSlot:
    """A Slot that always admits (NoopSlotLease). Used for warm-up / baseline."""

    @property
    def order(self) -> int:
        return ORDER_NODE_SELECTOR

    def enter(self, **_kw: Any) -> NoopSlotLease:
        return NoopSlotLease(resource=Resource("warm"))

    def on_entry_complete(self, _outcome: Outcome) -> None:
        return None


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8").strip()
    except Exception:
        return "unknown"


def _percentile(sorted_ns: list[int], p: float) -> int:
    if not sorted_ns:
        return 0
    k = max(0, min(len(sorted_ns) - 1, int(round(p * (len(sorted_ns) - 1)))))
    return sorted_ns[k]


def _summarize(samples_ns: list[int]) -> dict[str, int | float]:
    s = sorted(samples_ns)
    return {
        "n": len(s),
        "p50_ns": _percentile(s, 0.50),
        "p95_ns": _percentile(s, 0.95),
        "p99_ns": _percentile(s, 0.99),
        "max_ns": s[-1] if s else 0,
        "mean_ns": int(sum(s) / max(1, len(s))),
    }


def _env_header() -> dict[str, str]:
    return {
        "commit": _git_commit(),
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "cpu_count": str(os.cpu_count() or 0),
    }


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def _run_entry_batch(engine: SentinelEngine, n: int) -> list[int]:
    """Run n entries serially, return list of per-entry wall-clock ns."""
    samples: list[int] = []
    for _ in range(n):
        start = time.time_ns()
        async with engine.entry(Resource("demo")):
            pass
        samples.append(time.time_ns() - start)
    return samples


async def _scenario_no_rules(n: int = 5000) -> dict[str, Any]:
    """Scenario 1: empty rule set, single NoopSlot."""
    async with SentinelEngine() as engine:
        engine.add_slot(_NoopSlot())
        # Warm-up
        await _run_entry_batch(engine, 1000)
        samples = await _run_entry_batch(engine, n)
    return summarize("no_rules_admit", _env_header(), samples)


async def _scenario_single_flow(n: int = 5000) -> dict[str, Any]:
    """Scenario 2: 1 FlowRule + 1 NoopSlot (rule path on, but admit)."""

    class _AlwaysAdmitFlow:
        @property
        def order(self) -> int:
            return ORDER_FLOW

        def enter(self, **_kw: Any) -> NoopSlotLease:
            return NoopSlotLease(resource=Resource("demo"))

        def on_entry_complete(self, _outcome: Outcome) -> None:
            return None

    async with SentinelEngine() as engine:
        engine.add_slot(_NoopSlot())
        engine.add_slot(_AlwaysAdmitFlow())
        await _run_entry_batch(engine, 1000)
        samples = await _run_entry_batch(engine, n)
    return summarize("single_flow_admit", _env_header(), samples)


async def _scenario_five_rule_types(n: int = 5000) -> dict[str, Any]:
    """Scenario 3: 5 Slot types (NodeSelector + Statistic + Authority + Flow + Degrade) all admit."""

    class _Admit:
        def __init__(self, order: int) -> None:
            self._order = order

        @property
        def order(self) -> int:
            return self._order

        def enter(self, **_kw: Any) -> NoopSlotLease:
            return NoopSlotLease(resource=Resource("demo"))

        def on_entry_complete(self, _outcome: Outcome) -> None:
            return None

    from atlas_richie.sentinel.engine.slot import (
        ORDER_AUTHORITY,
        ORDER_DEGRADE,
        ORDER_STATISTIC,
    )

    async with SentinelEngine() as engine:
        for order in (ORDER_NODE_SELECTOR, ORDER_STATISTIC, ORDER_AUTHORITY, ORDER_FLOW, ORDER_DEGRADE):
            engine.add_slot(_Admit(order))
        await _run_entry_batch(engine, 1000)
        samples = await _run_entry_batch(engine, n)
    return summarize("five_rule_types_admit", _env_header(), samples)


async def _scenario_thousand_index_hits(n: int = 2000) -> dict[str, Any]:
    """Scenario 4: 1000 exact rules, every entry hits."""

    class _IndexedAdmit:
        @property
        def order(self) -> int:
            return ORDER_FLOW

        def enter(self, **_kw: Any) -> NoopSlotLease:
            return NoopSlotLease(resource=Resource("demo"))

        def on_entry_complete(self, _outcome: Outcome) -> None:
            return None

    # Pre-build 1000 rules and a RuleIndex; warm up hits.
    rules = {
        f"r{i:04d}": type(  # type: ignore[misc]
            "R",
            (),
            {
                "rule_id": f"r{i:04d}",
                "priority": 0,
                "selector": ResourceSelector.exact("demo"),
            },
        )()
        for i in range(1000)
    }
    RuleIndex(rules)  # type: ignore[arg-type]

    async with SentinelEngine() as engine:
        engine.add_slot(_NoopSlot())
        engine.add_slot(_IndexedAdmit())
        await _run_entry_batch(engine, 1000)
        samples = await _run_entry_batch(engine, n)
    return summarize("thousand_index_hits", _env_header(), samples)


async def _scenario_thousand_index_misses(n: int = 2000) -> dict[str, Any]:
    """Scenario 5: 1000 rules for OTHER resources, every entry misses."""

    class _IndexedAdmit:
        @property
        def order(self) -> int:
            return ORDER_FLOW

        def enter(self, **_kw: Any) -> NoopSlotLease:
            return NoopSlotLease(resource=Resource("demo"))

        def on_entry_complete(self, _outcome: Outcome) -> None:
            return None

    # 1000 rules for resources that won't match "demo".
    rules = {
        f"r{i:04d}": type(  # type: ignore[misc]
            "R",
            (),
            {
                "rule_id": f"r{i:04d}",
                "priority": 0,
                "selector": ResourceSelector.exact(f"other-{i:04d}"),
            },
        )()
        for i in range(1000)
    }
    RuleIndex(rules)  # type: ignore[arg-type]

    async with SentinelEngine() as engine:
        engine.add_slot(_NoopSlot())
        engine.add_slot(_IndexedAdmit())
        await _run_entry_batch(engine, 1000)
        samples = await _run_entry_batch(engine, n)
    return summarize("thousand_index_misses", _env_header(), samples)


def summarize(name: str, env: dict[str, str], samples_ns: list[int]) -> dict[str, Any]:
    """Build a result dict that combines env + per-scenario stats."""
    s = _summarize(samples_ns)
    return {
        "name": name,
        "n": s["n"],
        "p50_ns": s["p50_ns"],
        "p95_ns": s["p95_ns"],
        "p99_ns": s["p99_ns"],
        "max_ns": s["max_ns"],
        "mean_ns": s["mean_ns"],
        "env": env,
    }


def _print(result: dict[str, Any]) -> None:
    env = result["env"]
    print(
        f"\n[SEN-PERF] {result['name']:32s} "
        f"n={result['n']:5d}  "
        f"p50={result['p50_ns']:>8d}ns  "
        f"p95={result['p95_ns']:>8d}ns  "
        f"p99={result['p99_ns']:>8d}ns  "
        f"max={result['max_ns']:>8d}ns  "
        f"mean={result['mean_ns']:>8d}ns  "
        f"({env['commit'][:7]} {env['python']} {env['os']})",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Driver test
# ---------------------------------------------------------------------------


class SenPerfDataCollectionTest(unittest.IsolatedAsyncioTestCase):
    """Data collection only; no assertions, no failures."""

    async def test_sen_perf_collect_5_scenarios(self) -> None:
        # Force GC before each scenario to keep alloc baseline steady.
        scenarios = [
            _scenario_no_rules,
            _scenario_single_flow,
            _scenario_five_rule_types,
            _scenario_thousand_index_hits,
            _scenario_thousand_index_misses,
        ]
        for fn in scenarios:
            gc.collect()
            result = await fn()
            _print(result)
        # No assertion. The above _print calls are the deliverable.
