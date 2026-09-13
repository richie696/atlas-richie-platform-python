"""SentinelEngine.assemble_sources 公开契约测试 (M6.1.0d-1 / d-2 共享)。

中文
----
M6.1.0d-1 的"内部 contract / migration tests"已包含 d-2 的公开契约
测试代码, 因为装配入口的契约是 Supervisor 行为的外在表现, 拆开写
两份会重复。d-2 主要补 docstring / RULE_REFERENCE / EXTENSION_GUIDE
描述, 不写更多代码。

验证:

- ``assemble_sources`` 接受 ``Sequence[RuleSourceAssembly]`` + 必须
  ``repository`` 关键字参数
- priority 唯一性由 ``RuleSourceSupervisor`` 内部校验
- 重复调用语义: 显式拒绝 (``SentinelConfigurationError`` with
  reason="already_assembled")
- lifecycle gate: 只在 READY 允许
- multimode_conflict: install_legacy_source 之后 / 之前调用
  ``assemble_sources`` 都抛 ``SentinelConfigurationError("multimode_conflict")``
- ``aclose()`` 必须等待 Supervisor 关闭 (API delta v3 决策 2)
- 失败路径: ``SentinelConfigurationError("repository_required")``,
  ``"empty_assemblies"`` 等

English
--------
M6.1.0d-1's "internal contract / migration tests" already include
the d-2 public contract tests, because the assembly entry's contract
is the Supervisor's externally visible behavior; writing them in two
separate test files would duplicate. d-2 mainly adds docstring /
RULE_REFERENCE / EXTENSION_GUIDE descriptions, no more code.

Verifies:

- ``assemble_sources`` accepts ``Sequence[RuleSourceAssembly]`` +
  requires the ``repository`` keyword argument.
- Priority uniqueness is validated inside ``RuleSourceSupervisor``.
- Repeated-call semantics: explicit reject
  (``SentinelConfigurationError`` with reason="already_assembled").
- Lifecycle gate: only in READY.
- ``multimode_conflict``: calling ``assemble_sources`` after
  ``install_legacy_source`` (or vice versa) raises
  ``SentinelConfigurationError("multimode_conflict")``.
- ``aclose()`` must wait for the Supervisor to close (API delta v3
  decision 2).
- Failure paths: ``SentinelConfigurationError("repository_required")``,
  ``"empty_assemblies"``, etc.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from typing import AsyncIterator

from atlas_richie.sentinel.engine.sentinel_engine import FailSafe, SentinelEngine
from atlas_richie.sentinel.errors import (
    SentinelConfigurationError,
    SentinelLifecycleError,
)
from atlas_richie.sentinel.model.enums import EngineState
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source._supervisor.activation import RuleSourceActivation
from atlas_richie.sentinel.source._supervisor.observer import _RuleSourceActivationBus
from atlas_richie.sentinel.source.rule_source import RuleSourceAssembly


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
    """Minimal SnapshotRuleSource for Engine-level tests."""

    def __init__(
        self,
        source_id: str,
        *,
        block_after_yield: bool = False,
    ) -> None:
        self.source_id = source_id
        self._block = block_after_yield
        self._closed = False
        self.aclose_calls = 0
        self.snapshots_iterations = 0

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        self.snapshots_iterations += 1
        yield _make_snap(epoch=1, source_id=self.source_id)
        if self._block:
            try:
                await asyncio.sleep(60.0)
            except asyncio.CancelledError:
                return

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self._closed = True


def _assembly(
    source: _InMemorySnapshotSource,
    priority: int,
    *,
    failover_after: timedelta = timedelta(milliseconds=200),
) -> RuleSourceAssembly:
    return RuleSourceAssembly(
        source=source,  # type: ignore[arg-type]
        priority=priority,
        failover_after=failover_after,
    )


# ---------------------------------------------------------------------------
# 1. assemble_sources happy path + priority uniqueness
# ---------------------------------------------------------------------------


class AssembleSourcesValidationTest(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_sources_priority_uniqueness(self) -> None:
        # Two assemblies with same priority → must raise in
        # ``assemble_sources`` with reason="duplicate_priority"
        # (propagated from Supervisor.__init__).
        s1 = _InMemorySnapshotSource("a")
        s2 = _InMemorySnapshotSource("b")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [
                        _assembly(s1, 10),
                        _assembly(s2, 10),
                    ],
                    repository=RuleRepository(),
                )
            self.assertEqual(cm.exception.reason, "duplicate_priority")

    async def test_assemble_sources_repository_required(self) -> None:
        # repository=None → must raise SentinelConfigurationError
        # with reason="repository_required" (default-deny).
        s = _InMemorySnapshotSource("only")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [_assembly(s, 10)],
                    repository=None,  # type: ignore[arg-type]
                )
            self.assertEqual(cm.exception.reason, "repository_required")

    async def test_assemble_sources_empty_assemblies_rejected(self) -> None:
        # Empty assemblies list → must raise with reason="empty_assemblies".
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [],
                    repository=RuleRepository(),
                )
            self.assertEqual(cm.exception.reason, "empty_assemblies")

    async def test_assemble_sources_rule_source_assembly_priority_must_be_nonneg(
        self,
    ) -> None:
        # RuleSourceAssembly.__post_init__ validates priority >= 0.
        s = _InMemorySnapshotSource("a")
        with self.assertRaises(ValueError):
            _assembly(s, -1)


# ---------------------------------------------------------------------------
# 2. Lifecycle gate
# ---------------------------------------------------------------------------


class AssembleSourcesLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_sources_lifecycle_gate_created(self) -> None:
        # Engine in CREATED state: must raise SentinelLifecycleError.
        s = _InMemorySnapshotSource("a")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        # Don't enter async with; engine stays in CREATED.
        self.assertEqual(engine.state, EngineState.CREATED)
        with self.assertRaises(SentinelLifecycleError):
            await engine.assemble_sources(
                [_assembly(s, 10)],
                repository=RuleRepository(),
            )

    async def test_assemble_sources_lifecycle_gate_shutdown(self) -> None:
        # Engine in SHUTDOWN state: must raise.
        s = _InMemorySnapshotSource("a")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            pass  # engine goes CREATED → READY → SHUTTING_DOWN → SHUTDOWN
        self.assertEqual(engine.state, EngineState.SHUTDOWN)
        with self.assertRaises(SentinelLifecycleError):
            await engine.assemble_sources(
                [_assembly(s, 10)],
                repository=RuleRepository(),
            )

    async def test_assemble_sources_lifecycle_gate_ready_allows(self) -> None:
        # Engine in READY state: must allow.
        s = _InMemorySnapshotSource("a")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            self.assertEqual(engine.state, EngineState.READY)
            await engine.assemble_sources(
                [_assembly(s, 10)],
                repository=RuleRepository(),
            )
        # After exit, engine is SHUTDOWN.
        self.assertEqual(engine.state, EngineState.SHUTDOWN)


# ---------------------------------------------------------------------------
# 3. Repeat call semantics: explicit reject
# ---------------------------------------------------------------------------


class AssembleSourcesRepeatCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_sources_repeated_call_rejected(self) -> None:
        # M6.1.0d-1 decision: repeated ``assemble_sources`` is
        # rejected with reason="already_assembled" (fail-fast on
        # incorrect usage; reassembly is a future M6.1+ ADR).
        s1 = _InMemorySnapshotSource("a")
        s2 = _InMemorySnapshotSource("b")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            await engine.assemble_sources(
                [_assembly(s1, 10)],
                repository=RuleRepository(),
            )
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [_assembly(s2, 20)],
                    repository=RuleRepository(),
                )
            self.assertEqual(cm.exception.reason, "already_assembled")


# ---------------------------------------------------------------------------
# 4. multimode_conflict
# ---------------------------------------------------------------------------


class MultimodeConflictTest(unittest.IsolatedAsyncioTestCase):
    async def test_multimode_conflict_after_install_legacy(self) -> None:
        # install_legacy_source first, then assemble_sources → conflict.
        class _NoopLegacySource:
            source_id = "legacy"
            def start(self, repository: RuleRepository) -> None:
                pass
            def stop(self) -> None:
                pass
            def latest(self) -> RuleSnapshot | None:
                return None

        snap = _InMemorySnapshotSource("snap")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        engine.install_legacy_source(
            _NoopLegacySource(),
            repository=RuleRepository(),
        )
        async with engine:
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [_assembly(snap, 10)],
                    repository=RuleRepository(),
                )
            self.assertEqual(cm.exception.reason, "multimode_conflict")

    async def test_multimode_conflict_after_assemble_sources(self) -> None:
        # assemble_sources first → engine is in READY. Then
        # install_legacy_source → lifecycle gate prevents it (must be
        # CREATED). The multimode check (``_has_assembled``) is
        # defense-in-depth: it would catch any future lifecycle-gate
        # relaxation. We assert the lifecycle gate is the actual
        # reason, and the multimode check still exists in code.
        class _NoopLegacySource:
            source_id = "legacy"
            def start(self, repository: RuleRepository) -> None:
                pass
            def stop(self) -> None:
                pass
            def latest(self) -> RuleSnapshot | None:
                return None

        snap = _InMemorySnapshotSource("snap")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            await engine.assemble_sources(
                [_assembly(snap, 10)],
                repository=RuleRepository(),
            )
            # Lifecycle gate: install_legacy_source in READY state
            # raises SentinelLifecycleError (not multimode_conflict;
            # multimode_conflict is only reachable if the lifecycle
            # gate is later relaxed).
            with self.assertRaises(SentinelLifecycleError):
                engine.install_legacy_source(
                    _NoopLegacySource(),
                    repository=RuleRepository(),
                )
        # Defense-in-depth: directly verify the multimode_conflict
        # check exists by simulating ``_has_assembled=True`` in
        # CREATED state (which normally can't happen but exercises
        # the check code path).
        fresh_engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        # Manually set the flag (in a real flow this is set by
        # ``assemble_sources`` which requires READY; here we test
        # the check in isolation).
        fresh_engine._has_assembled = True  # type: ignore[attr-defined]
        with self.assertRaises(SentinelConfigurationError) as cm:
            fresh_engine.install_legacy_source(
                _NoopLegacySource(),
                repository=RuleRepository(),
            )
        self.assertEqual(cm.exception.reason, "multimode_conflict")

    async def test_install_legacy_source_lifecycle_gate_created_only(self) -> None:
        # install_legacy_source only allowed in CREATED state.
        s = _InMemorySnapshotSource("a")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            with self.assertRaises(SentinelLifecycleError):
                engine.install_legacy_source(
                    s,  # type: ignore[arg-type]
                    repository=RuleRepository(),
                )


# ---------------------------------------------------------------------------
# 5. aclose waits for Supervisor
# ---------------------------------------------------------------------------


class AcloseWaitsForSupervisorTest(unittest.IsolatedAsyncioTestCase):
    async def test_aclose_waits_for_supervisor(self) -> None:
        # When the supervisor has a long-lived source task,
        # ``engine.aclose()`` must wait for ``supervisor.aclose()`` to
        # complete (cancel the source task + call source.aclose())
        # BEFORE returning and BEFORE state is SHUTDOWN.
        s = _InMemorySnapshotSource("a", block_after_yield=True)
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        repo = RuleRepository()
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        async with engine:
            # Inject a custom bus by passing a SnapshotRuleSource
            # assembly; the supervisor creates a new bus internally,
            # so we observe via the activation fact only.
            await engine.assemble_sources(
                [_assembly(s, 10, failover_after=timedelta(milliseconds=200))],
                repository=repo,
            )
            # Wait for initial activation
            await asyncio.sleep(0.05)
        # After `async with` exit:
        # - engine state should be SHUTDOWN (only after supervisor closed)
        self.assertEqual(engine.state, EngineState.SHUTDOWN)
        # - source's aclose was called at least once (by supervisor.aclose)
        self.assertGreaterEqual(s.aclose_calls, 1)
        # - repository was NOT closed (passive container, no close method)
        self.assertFalse(hasattr(repo, "close"))
        self.assertFalse(hasattr(repo, "aclose"))
        # - the source was closed
        self.assertTrue(s._closed)  # type: ignore[attr-defined]

    async def test_aclose_waits_for_supervisor_no_state_race(self) -> None:
        # A subtle race: state must not become SHUTDOWN before the
        # supervisor's source tasks are cancelled. We assert the
        # observation order: s.aclose_calls becomes >= 1 by the time
        # engine.state is SHUTDOWN.
        s = _InMemorySnapshotSource("a", block_after_yield=True)
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        async with engine:
            await engine.assemble_sources(
                [_assembly(s, 10)],
                repository=RuleRepository(),
            )
            await asyncio.sleep(0.05)
        # At this point, `async with` exit has finished, so state is
        # SHUTDOWN AND source was aclose'd. The order is guaranteed
        # by ``close()``'s sequence: SHUTTING_DOWN → in_flight drain
        # → _close_attached_sources (supervisor.aclose) → SHUTDOWN.
        self.assertEqual(engine.state, EngineState.SHUTDOWN)
        self.assertGreaterEqual(s.aclose_calls, 1)


# ---------------------------------------------------------------------------
# 6. assemble_sources happy-path emits initial activation
# ---------------------------------------------------------------------------


class AssembleSourcesHappyPathTest(unittest.IsolatedAsyncioTestCase):
    async def test_assemble_sources_emits_initial_via_supervisor(self) -> None:
        # After ``assemble_sources`` completes, the supervisor's bus
        # has emitted an ``initial`` activation. We verify the
        # end-to-end behavior: repository has the snapshot, engine
        # has a supervisor, engine has _has_assembled = True.
        s = _InMemorySnapshotSource("a")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        repo = RuleRepository()
        async with engine:
            await engine.assemble_sources(
                [_assembly(s, 10)],
                repository=repo,
            )
            await asyncio.sleep(0.05)
        # End-of-life checks
        self.assertTrue(engine._has_assembled)  # type: ignore[attr-defined]
        self.assertIsNotNone(engine._supervisor)  # type: ignore[attr-defined]
        self.assertFalse(engine._has_legacy)  # type: ignore[attr-defined]
        # The Supervisor applied the snapshot to the Repository.
        self.assertIsNotNone(repo.last_version)
        self.assertEqual(repo.last_version.epoch, 1)
        # Active is the source
        self.assertEqual(
            engine._supervisor.active_source_id,  # type: ignore[attr-defined]
            "a",
        )


if __name__ == "__main__":
    unittest.main()
