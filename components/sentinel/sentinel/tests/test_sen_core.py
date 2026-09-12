"""SEN-CORE-001/002 baseline tests (M1.6).

中文
----
SEN-CORE = Sentinel 核心引擎 / Slot 协议 / Outcome 终态机的基线测试,
不依赖任何具体 rule (M2 才有),只验证:

- ``SentinelEngine`` 6 状态机 + async context manager 生命周期
- ``SlotChain`` 的 Order 升序遍历、stable sort、重复 id 拒绝
- 一次 entry 的 Slot 逆序释放语义(任一 Slot 抛 ``SentinelBlockedError``
  短路 + 已收 lease 逆序释放)
- Outcome 5 种状态(``ADMITTED`` / ``SUCCEEDED`` / ``FAILED`` /
  ``CANCELLED`` / ``BLOCKED``)严格互斥,**不**走二值化
- ``asyncio.CancelledError`` 业务执行中被取消时,lease 仍逆序释放
  (M1.3 完整语义)
- Slot 内部 ``RuntimeError`` 等非 ``SentinelError`` 异常,按
  ``FailSafe`` 三策略落地(FAIL_CLOSED / FAIL_OPEN / FAIL_FAST)
- 故障注入:lease ``release()`` 抛错不外泄(Sentinel Engine 内部
  swallow 到 ``last_error``)

不依赖任何 M2 规则;只用到 M1 公共 API。
对照 PLANNING §M1.6 + DESIGN §M1.2/M1.3。

English
--------
SEN-CORE-001/002 baseline tests (M1.6).

SEN-CORE is the baseline test surface for the Sentinel core engine,
Slot protocol, and Outcome state machine. It does not depend on any
specific rule (M2 introduces them); it only verifies:

- ``SentinelEngine`` 6-state machine + async context manager lifecycle.
- ``SlotChain`` order-ascending traversal, stable sort, duplicate-id reject.
- Single-entry Slot reverse release semantics (any Slot raising
  ``SentinelBlockedError`` short-circuits + already-collected leases
  are released in reverse).
- Outcome 5-way state (``ADMITTED`` / ``SUCCEEDED`` / ``FAILED`` /
  ``CANCELLED`` / ``BLOCKED``) is strictly mutually exclusive; **not**
  binary.
- ``asyncio.CancelledError`` during business execution: leases are still
  released in reverse (M1.3 full semantics).
- Slot-internal non-``SentinelError`` exceptions (e.g. ``RuntimeError``)
  are handled by ``FailSafe`` three strategies (FAIL_CLOSED / FAIL_OPEN
  / FAIL_FAST).
- Fault injection: lease ``release()`` raising does not propagate
  (Sentinel Engine swallows to ``last_error``).

No M2 rules are required; only the M1 public API is used.
Cross-ref PLANNING §M1.6 + DESIGN §M1.2/M1.3.
"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable
from typing import Any

from atlas_richie.sentinel.engine.sentinel_engine import FailSafe, SentinelEngine
from atlas_richie.sentinel.engine.slot import (
    ORDER_FLOW,
    ORDER_NODE_SELECTOR,
    ORDER_STATISTIC,
    ORDER_USER_MAX,
    Slot,
)
from atlas_richie.sentinel.engine.slot_chain import SlotChain
from atlas_richie.sentinel.errors import (
    SentinelBlockedError,
    SentinelConfigurationError,
    SentinelLifecycleError,
)
from atlas_richie.sentinel.model.argument import InvocationArguments
from atlas_richie.sentinel.model.context import SentinelContext
from atlas_richie.sentinel.model.decision import NoopSlotLease, SlotLease
from atlas_richie.sentinel.model.enums import BlockReason, EngineState
from atlas_richie.sentinel.model.outcome import OutcomeKind
from atlas_richie.sentinel.model.resource import Resource

from _helpers import CountingCall


# ---------------------------------------------------------------------------
# Test fixtures: ordered recording slots
# ---------------------------------------------------------------------------


class _RecordSlot:
    """Stub Slot that records enter / release order + returns a recordable lease.

    The Slot's ``order`` is a configurable integer; ``enter`` always returns
    a ``RecordingLease`` (which records release order); ``on_entry_complete``
    records the outcome.

    Used for: reverse-release verification, Order stable sort verification,
    CancelledError path verification.
    """

    def __init__(
        self,
        order: int,
        *,
        raise_block: SentinelBlockedError | None = None,
        lease_release_error: BaseException | None = None,
        global_releases: list[str] | None = None,
    ) -> None:
        self._order = order
        self._raise_block = raise_block
        self._lease_release_error = lease_release_error
        self.enter_calls: list[str] = []
        self.completion_calls: list[OutcomeKind] = []
        self.release_calls: list[str] = []
        # Optional global recorder so a test can assert the cross-slot
        # reverse release order in a single linearized list.
        self._global_releases = global_releases

    @property
    def order(self) -> int:
        return self._order

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        tag = f"slot@{self._order}"
        self.enter_calls.append(tag)
        if self._raise_block is not None:
            raise self._raise_block
        return RecordingLease(
            resource=resource,
            tag=tag,
            local_recorder=self.release_calls,
            global_recorder=self._global_releases,
            release_error=self._lease_release_error,
        )

    def on_entry_complete(self, outcome: Any) -> None:
        self.completion_calls.append(outcome.kind)


class RecordingLease:
    """Lease that records release order and supports fault injection."""

    def __init__(
        self,
        *,
        resource: Resource,
        tag: str,
        local_recorder: list[str],
        global_recorder: list[str] | None = None,
        release_error: BaseException | None = None,
    ) -> None:
        self._resource = resource
        self._tag = tag
        self._local_recorder = local_recorder
        self._global_recorder = global_recorder
        self._release_error = release_error
        self.released = False

    @property
    def resource(self) -> Resource:
        return self._resource

    async def release(self) -> None:
        # Idempotency: do not double-record
        if self.released:
            return
        self.released = True
        self._local_recorder.append(self._tag)
        if self._global_recorder is not None:
            self._global_recorder.append(self._tag)
        if self._release_error is not None:
            raise self._release_error


# ---------------------------------------------------------------------------
# SEN-CORE-001: Engine lifecycle / state machine
# ---------------------------------------------------------------------------


class SentinelEngineLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_engine_state_machine_legal_transitions(self) -> None:
        # CREATED → READY (via __aenter__) → SHUTDOWN (via __aexit__)
        engine = SentinelEngine()
        self.assertIs(engine.state, EngineState.CREATED)
        async with engine:
            self.assertIs(engine.state, EngineState.READY)
        self.assertIs(engine.state, EngineState.SHUTDOWN)

    async def test_double_aenter_raises_lifecycle_error(self) -> None:
        # Second __aenter__ from a non-CREATED state must raise
        # SentinelLifecycleError (state machine rejects illegal moves).
        engine = SentinelEngine()
        async with engine:
            with self.assertRaises(SentinelLifecycleError):
                await engine.__aenter__()

    async def test_entry_after_shutdown_raises_lifecycle_error(self) -> None:
        # entry() after SHUTDOWN must raise (not normalize to Outcome).
        engine = SentinelEngine()
        async with engine:
            pass
        self.assertIs(engine.state, EngineState.SHUTDOWN)
        with self.assertRaises(SentinelLifecycleError):
            engine.entry(Resource("demo"))

    async def test_add_slot_after_shutdown_raises(self) -> None:
        engine = SentinelEngine()
        async with engine:
            pass
        slot = _RecordSlot(order=ORDER_FLOW)
        with self.assertRaises(SentinelLifecycleError):
            engine.add_slot(slot)

    async def test_close_idempotent(self) -> None:
        engine = SentinelEngine()
        async with engine:
            pass
        # Multiple close() calls are safe no-ops.
        await engine.aclose()
        await engine.aclose()
        self.assertIs(engine.state, EngineState.SHUTDOWN)

    async def test_close_from_failed_state_is_noop(self) -> None:
        # FAILED → close() is allowed idempotently (not illegal transition).
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_FAST)
        await engine.__aenter__()
        # Add a slot that raises a non-Sentinel error on enter; FAIL_FAST
        # will transition to FAILED on first entry.
        slot = _RecordSlot(order=ORDER_FLOW)

        class _Boom:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(self, **_kw: Any) -> SlotLease:
                raise RuntimeError("boom")

            def on_entry_complete(self, _o: Any) -> None:
                pass

        engine.add_slot(slot)  # type: ignore[arg-type]
        engine.add_slot(_Boom())  # type: ignore[arg-type]
        with self.assertRaises(RuntimeError):
            async with engine.entry(Resource("demo")):
                pass
        self.assertIs(engine.state, EngineState.FAILED)
        await engine.aclose()  # no-op
        self.assertIs(engine.state, EngineState.FAILED)

    async def test_in_flight_increments_and_decrements(self) -> None:
        engine = SentinelEngine()
        async with engine:
            slot = _RecordSlot(order=ORDER_FLOW)
            engine.add_slot(slot)
            self.assertEqual(engine.in_flight, 0)

            async with engine.entry(Resource("demo")):
                self.assertEqual(engine.in_flight, 1)
            self.assertEqual(engine.in_flight, 0)
        self.assertEqual(len(slot.completion_calls), 1)


# ---------------------------------------------------------------------------
# SEN-CORE-001: SlotChain order / stable sort / duplicate
# ---------------------------------------------------------------------------


class SlotChainTest(unittest.IsolatedAsyncioTestCase):
    def test_frozen_slots_sorted_by_order_ascending(self) -> None:
        chain = SlotChain()
        s_flow = _RecordSlot(order=ORDER_FLOW)
        s_node = _RecordSlot(order=ORDER_NODE_SELECTOR)
        s_stat = _RecordSlot(order=ORDER_STATISTIC)
        # Insert in non-sorted order
        chain.add_slot(s_flow)
        chain.add_slot(s_node)
        chain.add_slot(s_stat)
        frozen = chain.frozen_slots()
        self.assertEqual([s.order for s in frozen], [ORDER_NODE_SELECTOR, ORDER_STATISTIC, ORDER_FLOW])

    def test_stable_sort_preserves_insertion_for_same_order(self) -> None:
        chain = SlotChain()
        a = _RecordSlot(order=ORDER_FLOW)
        b = _RecordSlot(order=ORDER_FLOW)
        c = _RecordSlot(order=ORDER_FLOW)
        chain.add_slot(a)
        chain.add_slot(b)
        chain.add_slot(c)
        frozen = chain.frozen_slots()
        self.assertEqual([id(s) for s in frozen], [id(a), id(b), id(c)])

    def test_duplicate_slot_id_raises_configuration_error(self) -> None:
        chain = SlotChain()
        slot = _RecordSlot(order=ORDER_FLOW)
        chain.add_slot(slot)
        with self.assertRaises(SentinelConfigurationError):
            chain.add_slot(slot)

    def test_non_positive_order_rejected(self) -> None:
        chain = SlotChain()
        bad = _RecordSlot(order=0)
        with self.assertRaises(SentinelConfigurationError):
            chain.add_slot(bad)

    def test_remove_slot_returns_false_for_unknown(self) -> None:
        chain = SlotChain()
        s = _RecordSlot(order=ORDER_FLOW)
        self.assertFalse(chain.remove_slot(s))
        chain.add_slot(s)
        self.assertTrue(chain.remove_slot(s))
        self.assertFalse(chain.remove_slot(s))

    def test_user_slot_order_in_allowed_range(self) -> None:
        # ORDER_USER_MIN < user < ORDER_USER_MAX is a documented band.
        # M1.2 does not enforce it at the chain layer (chain only enforces
        # > 0), so this test is a regression guard: ensure the constants
        # remain in a sensible range and that picking ORDER_FLOW works.
        self.assertLess(150, ORDER_FLOW)
        self.assertLess(ORDER_FLOW, ORDER_USER_MAX)


# ---------------------------------------------------------------------------
# SEN-CORE-001: Entry reverse release semantics
# ---------------------------------------------------------------------------


class EntryReverseReleaseTest(unittest.IsolatedAsyncioTestCase):
    async def test_all_admitted_leases_released_in_reverse_order(self) -> None:
        engine = SentinelEngine()
        # 3 slots in different orders; share a global release recorder
        # so we can assert the actual cross-slot reverse order.
        global_releases: list[str] = []
        s_node = _RecordSlot(order=ORDER_NODE_SELECTOR, global_releases=global_releases)
        s_stat = _RecordSlot(order=ORDER_STATISTIC, global_releases=global_releases)
        s_flow = _RecordSlot(order=ORDER_FLOW, global_releases=global_releases)
        async with engine:
            engine.add_slot(s_node)
            engine.add_slot(s_stat)
            engine.add_slot(s_flow)
            async with engine.entry(Resource("demo")):
                pass
        # enter order: node → stat → flow
        self.assertEqual(
            s_node.enter_calls + s_stat.enter_calls + s_flow.enter_calls,
            ["slot@100", "slot@200", "slot@500"],
        )
        # SlotChain collected leases in Order asc, so the last-collected
        # is the highest order (flow). release_all walks reversed → flow
        # must be released first, then stat, then node.
        self.assertEqual(global_releases, ["slot@500", "slot@200", "slot@100"])
        # Per-slot records also reflect a single release each.
        self.assertEqual(s_node.release_calls, ["slot@100"])
        self.assertEqual(s_stat.release_calls, ["slot@200"])
        self.assertEqual(s_flow.release_calls, ["slot@500"])

    async def test_blocked_short_circuit_releases_collected_leases_in_reverse(self) -> None:
        engine = SentinelEngine()
        global_releases: list[str] = []
        s_node = _RecordSlot(order=ORDER_NODE_SELECTOR, global_releases=global_releases)
        blocked_exc = SentinelBlockedError(
            "test block",
            block_reason=BlockReason.FLOW,
            resource=Resource("demo"),
            stable_code="FLOW_DEMO",
            rule_id="rule-1",
        )
        s_flow = _RecordSlot(order=ORDER_FLOW, raise_block=blocked_exc, global_releases=global_releases)
        s_after = _RecordSlot(order=ORDER_USER_MAX, global_releases=global_releases)
        async with engine:
            engine.add_slot(s_node)
            engine.add_slot(s_flow)
            engine.add_slot(s_after)
            with self.assertRaises(SentinelBlockedError):
                async with engine.entry(Resource("demo")):
                    pass
        # node entered + got lease; flow raises; after never enters.
        self.assertEqual(s_node.enter_calls, ["slot@100"])
        self.assertEqual(s_flow.enter_calls, ["slot@500"])
        self.assertEqual(s_after.enter_calls, [])
        # node's lease must still be released (only collected lease).
        self.assertEqual(global_releases, ["slot@100"])
        # flow's lease does not exist (raise before returning), so no release.
        self.assertEqual(s_flow.release_calls, [])

    async def test_lease_release_exception_is_swallowed(self) -> None:
        # A lease whose release() raises must not break the entry lifecycle.
        engine = SentinelEngine()
        boom = RuntimeError("release failure")
        slot = _RecordSlot(order=ORDER_FLOW, lease_release_error=boom)
        async with engine:
            engine.add_slot(slot)
            # Must not raise; engine swallows to last_error.
            async with engine.entry(Resource("demo")) as entry:
                pass
        # Entry completed normally even though lease.release() raised.
        self.assertEqual(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        # last_error reflects the swallowed exception
        self.assertIs(engine.last_error, boom)
        # lease.release() was called once (recording in slot.release_calls).
        self.assertEqual(slot.release_calls, ["slot@500"])

    async def test_lease_release_idempotency(self) -> None:
        # EntryLease.release_all() is idempotent; second entry on the
        # same engine must produce one additional release per slot
        # (not double-release the previous entry's lease).
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)
            async with engine.entry(Resource("demo")):
                pass
            # Second entry on the same live engine: lease release must
            # not double-count the first entry's lease.
            async with engine.entry(Resource("demo2")):
                pass
        # Each entry produced exactly one release record on the slot.
        self.assertEqual(slot.release_calls, ["slot@500", "slot@500"])


# ---------------------------------------------------------------------------
# SEN-CORE-001: Outcome 5-way state machine (mutual exclusivity)
# ---------------------------------------------------------------------------


class OutcomeKindTest(unittest.IsolatedAsyncioTestCase):
    async def test_admitted_outcome_for_blocked_path(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(
            order=ORDER_FLOW,
            raise_block=SentinelBlockedError(
                "x",
                block_reason=BlockReason.FLOW,
                resource=Resource("demo"),
                stable_code="FLOW_DEMO",
                rule_id="r",
            ),
        )
        async with engine:
            engine.add_slot(slot)
            with self.assertRaises(SentinelBlockedError):
                # BLOCKED path: __aenter__ raises before body runs, so
                # the ``as entry`` binding is never created. We assert
                # the BLOCKED outcome via ``engine.last_outcome`` instead.
                async with engine.entry(Resource("demo")):
                    self.fail("BLOCKED path should not reach body")
        self.assertEqual(engine.last_outcome.kind, OutcomeKind.BLOCKED)
        self.assertIsInstance(engine.last_outcome.error, SentinelBlockedError)
        self.assertEqual(engine.last_outcome.resource.name, "demo")

    async def test_succeeded_outcome_when_business_returns(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)
            async with engine.entry(Resource("demo")) as entry:
                pass
        self.assertEqual(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertIsNone(entry.outcome.error)

    async def test_failed_outcome_when_business_raises(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)
            with self.assertRaises(RuntimeError):
                async with engine.entry(Resource("demo")) as entry:
                    raise RuntimeError("business boom")
        self.assertEqual(entry.outcome.kind, OutcomeKind.FAILED)
        self.assertIsInstance(entry.outcome.error, RuntimeError)

    async def test_cancelled_outcome_when_cancelled_during_business(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)

            async def run_entry() -> None:
                async with engine.entry(Resource("demo")) as entry:
                    await asyncio.sleep(0.1)
                    self.fail("should not reach here")

            task = asyncio.create_task(run_entry())
            await asyncio.sleep(0.01)  # let the entry start
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        # We do not have direct access to the entry here (task ran in
        # another frame); assert via engine.last_outcome.
        self.assertIs(engine.last_outcome.kind, OutcomeKind.CANCELLED)
        self.assertIsInstance(engine.last_outcome.error, asyncio.CancelledError)

    async def test_outcome_kinds_are_strictly_distinct(self) -> None:
        # Defensive: 5 OutcomeKind values are mutually exclusive.
        kinds = {k.value for k in OutcomeKind}
        self.assertEqual(len(kinds), 5)


# ---------------------------------------------------------------------------
# SEN-CORE-001: FailSafe three strategies
# ---------------------------------------------------------------------------


class FailSafeTest(unittest.IsolatedAsyncioTestCase):
    async def test_fail_closed_rejects_on_slot_runtime_error(self) -> None:
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)

        class _Boom:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(self, **_kw: Any) -> SlotLease:
                raise RuntimeError("slot boom")

            def on_entry_complete(self, _o: Any) -> None:
                pass

        captured: dict[str, Any] = {}
        async with engine:
            engine.add_slot(_Boom())  # type: ignore[arg-type]
            # Under FAIL_CLOSED, a Slot RuntimeError must surface to caller.
            with self.assertRaises(RuntimeError):
                async with engine.entry(Resource("demo")) as entry:
                    captured["entry"] = entry
            # State stays READY under FAIL_CLOSED (one bad slot does not
            # poison the whole engine).
            self.assertIs(engine.state, EngineState.READY)
        # last_error recorded; engine still functional.
        self.assertIsInstance(engine.last_error, RuntimeError)
        # After async with, the engine transitions to SHUTDOWN.
        self.assertIs(engine.state, EngineState.SHUTDOWN)

    async def test_fail_open_admits_on_slot_runtime_error(self) -> None:
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_OPEN)

        class _Boom:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(self, **_kw: Any) -> SlotLease:
                raise RuntimeError("slot boom")

            def on_entry_complete(self, _o: Any) -> None:
                pass

        async with engine:
            engine.add_slot(_Boom())  # type: ignore[arg-type]
            async with engine.entry(Resource("demo")) as entry:
                pass
        # Entry succeeded (FAIL_OPEN admits).
        self.assertEqual(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        # last_error recorded for observability.
        self.assertIsInstance(engine.last_error, RuntimeError)

    async def test_fail_fast_transitions_to_failed_on_slot_runtime_error(self) -> None:
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_FAST)

        class _Boom:
            @property
            def order(self) -> int:
                return ORDER_FLOW

            def enter(self, **_kw: Any) -> SlotLease:
                raise RuntimeError("slot boom")

            def on_entry_complete(self, _o: Any) -> None:
                pass

        await engine.__aenter__()
        engine.add_slot(_Boom())  # type: ignore[arg-type]
        with self.assertRaises(RuntimeError):
            async with engine.entry(Resource("demo")):
                pass
        # Engine is now FAILED; further entry() raises.
        self.assertIs(engine.state, EngineState.FAILED)
        with self.assertRaises(SentinelLifecycleError):
            engine.entry(Resource("demo2"))


# ---------------------------------------------------------------------------
# SEN-CORE-001: Multi-entry concurrency (entry() returns synchronously)
# ---------------------------------------------------------------------------


class EntryConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_entries_each_get_independent_outcome(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)

            async def run(i: int) -> OutcomeKind:
                async with engine.entry(Resource(f"r-{i}")) as entry:
                    await asyncio.sleep(0.001)
                return entry.outcome.kind

            kinds = await asyncio.gather(*(run(i) for i in range(10)))
        self.assertEqual(kinds, [OutcomeKind.SUCCEEDED] * 10)
        self.assertEqual(slot.enter_calls, [f"slot@500"] * 10)
        # 10 release records, one per entry.
        self.assertEqual(slot.release_calls, [f"slot@500"] * 10)

    async def test_sequential_entries_isolate_state(self) -> None:
        engine = SentinelEngine()
        slot = _RecordSlot(order=ORDER_FLOW)
        async with engine:
            engine.add_slot(slot)
            for _ in range(5):
                async with engine.entry(Resource("x")) as entry:
                    pass
                self.assertEqual(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertEqual(len(slot.completion_calls), 5)


# ---------------------------------------------------------------------------
# SEN-CORE-001: NoopSlotLease sentinel (used by ParamFlowSlot, M2)
# ---------------------------------------------------------------------------


class NoopSlotLeaseTest(unittest.IsolatedAsyncioTestCase):
    async def test_noop_lease_release_is_idempotent(self) -> None:
        lease = NoopSlotLease(resource=Resource("demo"))
        # Calling release() multiple times is a no-op.
        await lease.release()
        await lease.release()
        await lease.release()
        self.assertEqual(lease.resource.name, "demo")


# ---------------------------------------------------------------------------
# SEN-CORE-001: Engine with NO rules (the M1 Exit demo path)
# ---------------------------------------------------------------------------


class EngineWithNoRulesTest(unittest.IsolatedAsyncioTestCase):
    """Mirrors the M1 Exit demo: empty rule set + 1 business entry.

    This is the smoke test that the M1 Exit demo relies on.
    """

    async def test_empty_engine_admits_arbitrary_resource(self) -> None:
        async with SentinelEngine() as engine:
            async with engine.entry(Resource("demo")) as entry:
                await asyncio.sleep(0.001)
        self.assertEqual(entry.outcome.kind, OutcomeKind.SUCCEEDED)
        self.assertIsNone(entry.outcome.error)
        self.assertGreaterEqual(entry.outcome.elapsed_ns, 0)


# ---------------------------------------------------------------------------
# Helper integration: CountingCall from _helpers.py
# ---------------------------------------------------------------------------


class HelpersIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_counting_call_records_invocations(self) -> None:
        # Sanity check: _helpers.CountingCall works as documented so the
        # SEN-CORE tests can rely on it in M2.
        c = CountingCall(value=42)
        results = [await c() for _ in range(3)]
        self.assertEqual(results, [42, 42, 42])
        self.assertEqual(c.calls, 3)


if __name__ == "__main__":
    unittest.main()
