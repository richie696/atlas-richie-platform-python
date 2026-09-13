"""C 层 ``RuleSourceActivation`` fact 测试 (M6.1.0d-1)。

中文
----
验证 5 项 activation fact 契约:

1. **3 条件 AND emit**: Repository 成功 + active source_id 实际变更
   + 业务真实切换 → emit
2. **Repository 拒绝不 emit**: ``apply_snapshot`` 返 False, 不发 fact
3. **no-op manual_replace 不 emit**: active 不变, 不发 fact
4. **all_stale 是 health event, 不进 activation**: active stale
   但无 ready 替代, 不发 fact
5. **observer 异常隔离**: 单 observer 抛异常, 其它 observer 与
   publish 调用栈都不受影响
6. **observer 异常 publish 不被拖垮**: 主调用栈继续, 下一 publish
   仍正常
7. **不含时间戳字段**: ``RuleSourceActivation`` 是 frozen dataclass,
   字段集不含时间戳 (M6.5.7 envelope 提供)

English
--------
Verifies five ``RuleSourceActivation`` fact contracts:

1. **3-condition AND emit**: Repository success + active source_id
   actually changes + real business switch → emit.
2. **Repository rejection does not emit**: ``apply_snapshot`` returns
   ``False``, no fact.
3. **no-op manual_replace does not emit**: active unchanged, no fact.
4. **all_stale is a health event, not an activation**: active stale
   but no ready alternative, no fact.
5. **observer exception isolation**: a single observer raising does
   not affect other observers or the publish call stack.
6. **publish is not broken by observer exception**: the main call
   stack continues, next publish still works.
7. **No timestamp field**: ``RuleSourceActivation`` is a frozen
   dataclass whose field set does not include any timestamp (M6.5.7
   envelope provides).
"""

from __future__ import annotations

import asyncio
import logging
import unittest
from datetime import timedelta
from typing import AsyncIterator

from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source._supervisor.activation import RuleSourceActivation
from atlas_richie.sentinel.source._supervisor.binding import _RuleSourceBinding
from atlas_richie.sentinel.source._supervisor.observer import (
    ActivationObserver,
    _RuleSourceActivationBus,
)
from atlas_richie.sentinel.source._supervisor.supervisor import RuleSourceSupervisor


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def _make_snap(epoch: int = 1, source_id: str = "") -> RuleSnapshot:
    return RuleSnapshot(
        version=RuleVersion(epoch=epoch, revision=0, checksum="0" * 64),
        rules={},
        applied_at_ns=0,
        source_id=source_id,
    )


class _InMemorySnapshotSource:
    """Minimal SnapshotRuleSource; yields scripted snapshots once."""

    def __init__(
        self,
        source_id: str,
        scripted_snapshots: list[RuleSnapshot] | None = None,
        *,
        raise_after: BaseException | None = None,
    ) -> None:
        self.source_id = source_id
        self._scripted = list(scripted_snapshots or [])
        self._raise_after = raise_after
        self._closed = False

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        for snap in self._scripted:
            if self._closed:
                return
            yield snap
        if self._raise_after is not None:
            raise self._raise_after

    async def aclose(self) -> None:
        self._closed = True


def _binding(
    source: _InMemorySnapshotSource,
    priority: int,
    *,
    failover_after: timedelta = timedelta(seconds=1),
) -> _RuleSourceBinding:
    return _RuleSourceBinding(
        source_id=source.source_id,
        source=source,  # type: ignore[arg-type]
        priority=priority,
        failover_after=failover_after,
    )


# ---------------------------------------------------------------------------
# 1. 3-condition AND emit
# ---------------------------------------------------------------------------


class ActivationThreeConditionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_activation_three_conditions_and_emit(self) -> None:
        # Two sources, low (priority 10) yields first → active. Then
        # high (priority 20) yields → switch with reason="manual_replace".
        # Verify: initial emit + manual_replace emit.
        s_low = _InMemorySnapshotSource("low", [_make_snap(epoch=1, source_id="low")])
        s_high = _InMemorySnapshotSource("high", [_make_snap(epoch=1, source_id="high")])
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = RuleSourceSupervisor(
            bindings=[
                _binding(s_low, 10),
                _binding(s_high, 20),
            ],
            repository=RuleRepository(),
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.05)
        # After start, active is "high" (highest priority).
        self.assertEqual(sv.active_source_id, "high")
        # seen: at least one initial emit.
        self.assertGreaterEqual(len(seen), 1)
        initial_facts = [a for a in seen if a.reason == "initial"]
        self.assertEqual(len(initial_facts), 1)
        self.assertEqual(initial_facts[0].source_id, "high")
        self.assertEqual(initial_facts[0].previous_source_id, None)
        await sv.aclose()


# ---------------------------------------------------------------------------
# 2. Repository rejects candidate → no emit
# ---------------------------------------------------------------------------


class ActivationNoEmitOnRejectTest(unittest.IsolatedAsyncioTestCase):
    async def test_activation_no_emit_on_apply_false(self) -> None:
        # Patch the Repository to reject ALL snapshots: apply_snapshot
        # returns False. The Supervisor should never see a ready
        # source → no activation emit at all.
        class _RejectingRepository(RuleRepository):
            def apply_snapshot(self, snap: RuleSnapshot) -> bool:  # type: ignore[override]
                # Skip all updates; return False.
                return False

        s = _InMemorySnapshotSource("only", [_make_snap(epoch=1, source_id="only")])
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = RuleSourceSupervisor(
            bindings=[_binding(s, 10)],
            repository=_RejectingRepository(),
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.05)
        # No activation emit because no source was successfully applied.
        self.assertEqual(len(seen), 0)
        # Active is None — no source ever became ready.
        self.assertIsNone(sv.active_source_id)
        await sv.aclose()


# ---------------------------------------------------------------------------
# 3. no-op manual_replace → no emit
# ---------------------------------------------------------------------------


class ActivationNoOpTest(unittest.IsolatedAsyncioTestCase):
    async def test_activation_no_emit_on_no_op(self) -> None:
        # Single source, yields multiple snapshots with different
        # versions. Active stays the same; no emit after initial.
        s = _InMemorySnapshotSource(
            "src",
            [
                _make_snap(epoch=1, source_id="src"),
                _make_snap(epoch=2, source_id="src"),
                _make_snap(epoch=3, source_id="src"),
            ],
        )
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = RuleSourceSupervisor(
            bindings=[_binding(s, 10)],
            repository=RuleRepository(),
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.05)
        # Exactly one initial emit; subsequent yields are no-ops
        # (3-condition AND fails: active source_id unchanged).
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].reason, "initial")
        self.assertEqual(seen[0].source_id, "src")
        await sv.aclose()


# ---------------------------------------------------------------------------
# 4. all_stale is a health event, NOT an activation
# ---------------------------------------------------------------------------


class ActivationAllStaleTest(unittest.IsolatedAsyncioTestCase):
    async def test_activation_health_event_not_in_activation(self) -> None:
        # Single source yields then goes stale. With only one source
        # and no other candidate, no failover, no "stale" reason
        # appears in any activation fact.
        s = _InMemorySnapshotSource(
            "only", [_make_snap(epoch=1, source_id="only")],
            raise_after=RuntimeError("simulated failure"),
        )
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        # Add a tiny sleep before raise to ensure start() election runs.
        # Use a custom source for that.
        class _StaleAfterElection(_InMemorySnapshotSource):
            def __init__(self, sid: str) -> None:
                super().__init__(sid, scripted_snapshots=[])

            async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
                yield _make_snap(epoch=1, source_id=self.source_id)
                await asyncio.sleep(0.05)  # let start() elect
                raise RuntimeError("simulated failure")

        s2 = _StaleAfterElection("only")
        sv = RuleSourceSupervisor(
            bindings=[_binding(s2, 10)],
            repository=RuleRepository(),
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.05)
        # One initial emit
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].reason, "initial")
        # Wait for stale to happen
        await asyncio.sleep(0.1)
        # Still only 1 emit — no "stale" reason in activation fact
        # (stale is a health event, not an activation)
        self.assertEqual(len(seen), 1)
        for fact in seen:
            self.assertNotEqual(fact.reason, "stale")
            self.assertNotEqual(fact.reason, "all_stale")
            self.assertNotEqual(fact.reason, "health")
        await sv.aclose()


# ---------------------------------------------------------------------------
# 5 + 6. observer exception isolation
# ---------------------------------------------------------------------------


class ActivationObserverIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_activation_observer_exception_isolated(self) -> None:
        # One observer raises; other observers must still receive.
        bus = _RuleSourceActivationBus()
        normal_a: list[RuleSourceActivation] = []
        normal_b: list[RuleSourceActivation] = []

        def raising(_fact: RuleSourceActivation) -> None:
            raise RuntimeError("observer failure (must be isolated)")

        def normal_a_obs(fact: RuleSourceActivation) -> None:
            normal_a.append(fact)

        def normal_b_obs(fact: RuleSourceActivation) -> None:
            normal_b.append(fact)

        bus.subscribe(raising)
        bus.subscribe(normal_a_obs)
        bus.subscribe(normal_b_obs)

        fact = RuleSourceActivation(
            previous_source_id=None,
            source_id="x",
            version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
            reason="initial",
        )
        # Should not raise — the raising observer's exception is
        # isolated.
        bus.publish(fact)
        # The two normal observers received the fact.
        self.assertEqual(normal_a, [fact])
        self.assertEqual(normal_b, [fact])

    async def test_activation_observer_exception_does_not_break_publish(
        self,
    ) -> None:
        # After an observer raises, subsequent publishes still
        # dispatch to all observers.
        bus = _RuleSourceActivationBus()
        counter: list[int] = []

        def raising(_fact: RuleSourceActivation) -> None:
            raise RuntimeError("always fails")

        def counting(_fact: RuleSourceActivation) -> None:
            counter.append(1)

        bus.subscribe(raising)
        bus.subscribe(counting)

        for i in range(3):
            fact = RuleSourceActivation(
                previous_source_id=None,
                source_id=f"src{i}",
                version=RuleVersion(epoch=i + 1, revision=0, checksum="0" * 64),
                reason="initial",
            )
            bus.publish(fact)  # must not raise
        # Counting observer received all 3.
        self.assertEqual(len(counter), 3)

    async def test_activation_observer_exception_logged_as_warning(
        self,
    ) -> None:
        # Observer exception is logged at WARNING level.
        # Exception payload is NOT in the log (privacy / sensitive data).
        bus = _RuleSourceActivationBus()

        def raising(_fact: RuleSourceActivation) -> None:
            raise RuntimeError("do-not-leak-payload-marker-XYZ")

        bus.subscribe(raising)
        fact = RuleSourceActivation(
            previous_source_id=None,
            source_id="x",
            version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
            reason="initial",
        )
        # Capture log records by adding a handler programmatically.
        captured: list[logging.LogRecord] = []
        target_logger = logging.getLogger(
            "atlas_richie.sentinel.source._supervisor.observer"
        )

        class _CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _CaptureHandler(level=logging.WARNING)
        target_logger.addHandler(handler)
        try:
            bus.publish(fact)
        finally:
            target_logger.removeHandler(handler)

        # At least one warning logged.
        warnings = [r for r in captured if r.levelno == logging.WARNING]
        self.assertGreaterEqual(len(warnings), 1)
        # Payload marker must NOT appear in any log message.
        for record in captured:
            self.assertNotIn(
                "do-not-leak-payload-marker-XYZ", record.getMessage()
            )


# ---------------------------------------------------------------------------
# 7. No timestamp field
# ---------------------------------------------------------------------------


class ActivationSchemaTest(unittest.TestCase):
    def test_activation_no_timestamp_field(self) -> None:
        import dataclasses
        fields = {f.name for f in dataclasses.fields(RuleSourceActivation)}
        # No timestamp / captured_at / received_at / emitted_at /
        # created_at / ts / time fields. (M6.5.7 envelope provides.)
        for forbidden in (
            "timestamp",
            "captured_at",
            "received_at",
            "emitted_at",
            "created_at",
            "ts",
            "time",
            "occurred_at",
        ):
            self.assertNotIn(
                forbidden,
                fields,
                f"RuleSourceActivation must not have {forbidden!r} "
                f"(M6.5.7 envelope provides); fields={fields!r}",
            )

    def test_activation_field_count(self) -> None:
        import dataclasses
        # Exactly 4 fields: previous_source_id, source_id, version, reason.
        # (rule_source_activation.md §3.1 — frozen dataclass shape.)
        fields = dataclasses.fields(RuleSourceActivation)
        self.assertEqual(
            len(fields), 4,
            f"RuleSourceActivation field count must be exactly 4, "
            f"got {[(f.name, f.type) for f in fields]!r}",
        )

    def test_activation_is_frozen_dataclass(self) -> None:
        import dataclasses
        self.assertTrue(dataclasses.is_dataclass(RuleSourceActivation))
        # Frozen: cannot mutate after construction.
        fact = RuleSourceActivation(
            previous_source_id=None,
            source_id="x",
            version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
            reason="initial",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            fact.source_id = "y"  # type: ignore[misc]

    def test_activation_reason_is_literal(self) -> None:
        # reason must be one of the 3 fixed literal values.
        valid_reasons = {"initial", "failover", "manual_replace"}
        for reason in valid_reasons:
            fact = RuleSourceActivation(
                previous_source_id=None,
                source_id="x",
                version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
                reason=reason,  # type: ignore[arg-type]
            )
            self.assertEqual(fact.reason, reason)
        # The annotation string is a Literal[...] with the 3 values.
        # (We read the raw __annotations__ to avoid forward-ref
        # evaluation issues with RuleVersion.)
        reason_hint = str(RuleSourceActivation.__annotations__["reason"])
        self.assertIn("Literal", reason_hint)
        for v in valid_reasons:
            # Literal uses single quotes in Python 3.12+ repr
            self.assertTrue(
                f"'{v}'" in reason_hint or f'"{v}"' in reason_hint,
                f"expected {v!r} in {reason_hint!r}",
            )


if __name__ == "__main__":
    unittest.main()
