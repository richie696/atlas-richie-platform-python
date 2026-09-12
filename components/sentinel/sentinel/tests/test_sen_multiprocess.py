"""M3.6: Multi-worker (per-process) semantics test.

中文
----
Sentinel 是**per-process** 状态机:每个 Python 进程有独立的
``SentinelEngine``、独立的 ``RuleRepository``、独立的指标计数器。
多 worker 部署(uvicorn ``--workers N`` / gunicorn workers)时:

- 同一份规则被加载 N 次,每个 worker 各自独立计数
- ``threshold=5`` 配 ``workers=2`` **不**等于"集群 5 QPS";实际
  上限 ≈ ``2 × threshold``(如果负载均分)+ 各种调度抖动
- Dashboard / metrics 看到的是**单 worker** 数据,不是"整个服务"

PLANNING §M3.6 Exit Criteria:

- 启动 2 个独立 Engine 实例(模拟 2 个 worker)
- 验证每个 Engine 的状态完全独立
- **不**断言 "threshold × workers = capacity"
- 文档明确:per-process 语义,Cluster 模式才有跨 worker 精确总量

本测试用 ``multiprocessing`` 启动 2 个真子进程,各自创建独立
Engine。**不**走 uvicorn / gunicorn(测试不引入 web server dep)。

English
--------
M3.6: Multi-worker (per-process) semantics test.

Sentinel is a **per-process** state machine: each Python process has
its own ``SentinelEngine``, ``RuleRepository``, and metric counters.
Under multi-worker deployment (uvicorn ``--workers N`` / gunicorn
workers):

- The same rules are loaded N times; each worker counts independently.
- ``threshold=5`` with ``workers=2`` does **not** equal "cluster 5 QPS";
  effective ceiling ≈ ``2 × threshold`` (if load is balanced) + various
  scheduling jitter.
- Dashboard / metrics show **single-worker** data, not "whole service".

PLANNING §M3.6 Exit Criteria:

- Start 2 independent Engine instances (simulating 2 workers).
- Verify each Engine's state is fully isolated.
- **Do not** assert "threshold × workers = capacity".
- Document: per-process semantics; Cluster mode is required for
  cross-worker exact totals.

This test uses ``multiprocessing`` to spawn 2 real subprocesses, each
creating its own Engine. We don't run uvicorn / gunicorn (test does
not introduce a web server dependency).
"""

from __future__ import annotations

import multiprocessing
import os
import unittest
from typing import Any

from atlas_richie.sentinel.engine import SentinelEngine
from atlas_richie.sentinel.engine.slot import (
    ORDER_FLOW,
    Slot,
)
from atlas_richie.sentinel.model.argument import InvocationArguments
from atlas_richie.sentinel.model.context import SentinelContext
from atlas_richie.sentinel.model.decision import NoopSlotLease
from atlas_richie.sentinel.model.outcome import Outcome
from atlas_richie.sentinel.model.resource import Resource


# ---------------------------------------------------------------------------
# Worker process entry points
# ---------------------------------------------------------------------------


def _count_admitted_in_worker(
    worker_id: str,
    n_attempts: int,
    result_queue: "multiprocessing.Queue[Any]",
) -> None:
    """Worker entry: create a fresh Engine, run n entries, return admitted count.

    No shared state with parent; each worker has its own process,
    its own imports, its own engine.
    """
    engine = SentinelEngine()
    admitted = 0
    try:
        # Slot that always admits (a noop node selector + a flow slot
        # that admits). We don't install a flow rule so all n succeed.
        class _Admit:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(
                self, *, resource: Resource, context: SentinelContext, args: InvocationArguments | None
            ) -> NoopSlotLease:
                return NoopSlotLease(resource=resource)

            def on_entry_complete(self, _o: Outcome) -> None:
                pass

        async def run() -> int:
            count = 0
            async with engine:
                engine.add_slot(_Admit())  # type: ignore[arg-type]
                for _ in range(n_attempts):
                    async with engine.entry(Resource(f"{worker_id}-resource")):
                        pass
                    if engine.last_outcome is not None:
                        if engine.last_outcome.kind.value == "succeeded":
                            count += 1
            return count

        admitted = asyncio_run(run())
    finally:
        result_queue.put((worker_id, admitted, os.getpid()))


def asyncio_run(coro: Any) -> Any:
    """Helper to run an async coroutine in a worker process."""
    import asyncio
    return asyncio.run(coro)


def _worker_a_apply(q: "multiprocessing.Queue[Any]") -> None:
    from atlas_richie.sentinel.rules.repository import RuleRepository
    from atlas_richie.sentinel.rules.snapshot import (
        RuleSnapshot,
        RuleVersion,
    )
    repo = RuleRepository()
    body = {"r1": {"type": "flow"}}
    v = RuleVersion(
        epoch=1, revision=0, checksum=RuleVersion.compute_checksum(body)
    )
    snap = RuleSnapshot(version=v, rules={}, source_id="worker-A")
    ok = repo.apply_snapshot(snap)
    q.put(("A", ok, repo.last_version is not None))


def _worker_b_empty(q: "multiprocessing.Queue[Any]") -> None:
    from atlas_richie.sentinel.rules.repository import RuleRepository
    repo = RuleRepository()
    # Worker B has its own process; should NOT see worker A's snapshot.
    q.put(("B", repo.last_version))


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class MultiWorkerPerProcessSemanticsTest(unittest.TestCase):
    """Verify per-process isolation of Engine state."""

    def test_two_workers_have_independent_state(self) -> None:
        # Two separate processes, each with its own Engine. Verify
        # their pid differs and admitted counts are independent.
        ctx = multiprocessing.get_context("spawn")
        q: Any = ctx.Queue()
        procs = [
            ctx.Process(
                target=_count_admitted_in_worker,
                args=("worker-A", 5, q),
            ),
            ctx.Process(
                target=_count_admitted_in_worker,
                args=("worker-B", 7, q),
            ),
        ]
        for p in procs:
            p.start()
        results = []
        for _ in procs:
            results.append(q.get(timeout=30))
        for p in procs:
            p.join(timeout=10)
        # Two distinct worker ids.
        ids = sorted(r[0] for r in results)
        self.assertEqual(ids, ["worker-A", "worker-B"])
        # Two distinct PIDs (true per-process isolation).
        pids = sorted(r[2] for r in results)
        self.assertEqual(len(set(pids)), 2)
        # Each worker admitted all its attempts (no shared state, no
        # coordination; each Engine is independent).
        by_id = {r[0]: r[1] for r in results}
        self.assertEqual(by_id["worker-A"], 5)
        self.assertEqual(by_id["worker-B"], 7)

    def test_two_workers_do_not_share_repository_state(self) -> None:
        # Two workers, each with its own RuleRepository. Worker A
        # applies snapshot; Worker B should NOT see it (per-process).
        ctx = multiprocessing.get_context("spawn")
        q: Any = ctx.Queue()
        p1 = ctx.Process(target=_worker_a_apply, args=(q,))
        p2 = ctx.Process(target=_worker_b_empty, args=(q,))
        p1.start(); p2.start()
        results = [q.get(timeout=30) for _ in range(2)]
        p1.join(timeout=10); p2.join(timeout=10)
        by_id = {r[0]: r[1:] for r in results}
        # Worker A's apply was successful (its local repo saw the snapshot).
        self.assertEqual(by_id["A"][0], True)
        self.assertEqual(by_id["A"][1], True)
        # Worker B's repository is empty (no shared state).
        self.assertEqual(by_id["B"][0], None)


class MultiWorkerInProcessSemanticsTest(unittest.IsolatedAsyncioTestCase):
    """In-process analog: two Engines running side-by-side.

    This is not a true cross-process test (no multiprocessing), but
    it documents the per-Engine isolation contract for users running
    multiple Sentinels in the same process.
    """

    async def test_two_engines_have_independent_inflight(self) -> None:
        engine_a = SentinelEngine()
        engine_b = SentinelEngine()
        async with engine_a, engine_b:
            self.assertEqual(engine_a.in_flight, 0)
            self.assertEqual(engine_b.in_flight, 0)
            # Hold engine A in-flight; engine B unaffected.
            await engine_a.entry(Resource("a")).__aenter__()
            self.assertEqual(engine_a.in_flight, 1)
            self.assertEqual(engine_b.in_flight, 0)
            await engine_a.entry(Resource("a")).__aexit__(None, None, None)
            self.assertEqual(engine_a.in_flight, 0)
            self.assertEqual(engine_b.in_flight, 0)


if __name__ == "__main__":
    unittest.main()
