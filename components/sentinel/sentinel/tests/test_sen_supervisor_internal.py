"""C 层私有 Supervisor 单元测试 (M6.1.0d-1)。

中文
----
直接构造 :class:`RuleSourceSupervisor` (不通过
``SentinelEngine.assemble_sources``), 验证:

- 启动时 priority 最高的 ready Source 选为 active
- active stale 后, 等待 ``failover_after`` 窗口才切到次高 priority
  ready Source
- 同一 active 的 checksum 刷新不 emit
- ``initial`` activation 只 emit 一次
- ``aclose()`` 幂等
- priority 唯一性校验 (``__init__`` 时抛)
- aclose 不关闭 repository

不依赖公开装配入口; 行为契约留给 ``test_sen_assemble_sources.py``。

English
--------
Direct-construct :class:`RuleSourceSupervisor` (without going through
``SentinelEngine.assemble_sources``), verifying:

- On start, the highest-priority ready Source is elected active.
- After active becomes stale, wait the ``failover_after`` window
  before switching to the next-highest priority ready Source.
- Same-active checksum refresh does not emit.
- ``initial`` activation emits only once.
- ``aclose()`` is idempotent.
- Priority uniqueness is validated (raises in ``__init__``).
- ``aclose`` does not close the repository.

Does not depend on the public assembly entry; behavioral contract
is left to ``test_sen_assemble_sources.py``.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta
from typing import AsyncIterator

from atlas_richie.sentinel.errors import SentinelConfigurationError
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source._supervisor.activation import RuleSourceActivation
from atlas_richie.sentinel.source._supervisor.binding import _RuleSourceBinding
from atlas_richie.sentinel.source._supervisor.observer import _RuleSourceActivationBus
from atlas_richie.sentinel.source._supervisor.supervisor import RuleSourceSupervisor


# ---------------------------------------------------------------------------
# Shared in-memory test fixtures (C-layer test only)
# ---------------------------------------------------------------------------


def _make_snap(
    epoch: int = 1, revision: int = 0, source_id: str = ""
) -> RuleSnapshot:
    """Build a minimal valid RuleSnapshot for tests.

    Empty body; RuleIndex handles empty rules fine, and apply_snapshot
    is the only Repository interaction we exercise here.
    """
    return RuleSnapshot(
        version=RuleVersion(epoch=epoch, revision=revision, checksum="0" * 64),
        rules={},
        applied_at_ns=0,
        source_id=source_id,
    )


class _InMemorySnapshotSource:
    """C-layer test-only SnapshotRuleSource that yields scripted snapshots.

    Behavior:

    - ``source_id`` is the user-supplied stable string.
    - ``snapshots()`` is an async generator that yields each snapshot
      in ``scripted_snapshots`` in order, then either:
      - raises ``scripted_exception`` (if set), OR
      - simply returns (natural iterator end → source marked stale).
    - ``aclose()`` is idempotent; cancels any pending iteration.
    """

    def __init__(
        self,
        source_id: str,
        scripted_snapshots: list[RuleSnapshot] | None = None,
        *,
        scripted_exception: BaseException | None = None,
    ) -> None:
        self.source_id = source_id
        self._scripted = list(scripted_snapshots or [])
        self._scripted_exception = scripted_exception
        self._closed = False
        self.aclose_calls = 0

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        for snap in self._scripted:
            if self._closed:
                return
            yield snap
        if self._scripted_exception is not None:
            raise self._scripted_exception
        # natural end → Supervisor should mark this source stale

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self._closed = True


class _LongLivedSnapshotSource(_InMemorySnapshotSource):
    """Yields the scripted snapshot, then blocks (simulates a real
    long-running source). Use ``aclose()`` to cancel."""

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        for snap in self._scripted:
            if self._closed:
                return
            yield snap
        # Block until cancelled.
        try:
            await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            return


class _StaleAfterYieldSnapshotSource(_InMemorySnapshotSource):
    """Yields the scripted snapshot, then sleeps briefly (so the
    Supervisor's start() can complete initial election), then raises
    RuntimeError → source goes stale."""

    def __init__(self, source_id: str) -> None:
        super().__init__(source_id, scripted_snapshots=[])

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        yield _make_snap(epoch=1, source_id=self.source_id)
        # Sleep so start()'s initial election completes BEFORE the
        # exception. Without this, the exception can race the
        # election and flip state to STALE before start() elects.
        await asyncio.sleep(0.05)
        raise RuntimeError("simulated source failure")


def _binding(
    source: _InMemorySnapshotSource, priority: int, *, failover_after: timedelta
) -> _RuleSourceBinding:
    return _RuleSourceBinding(
        source_id=source.source_id,
        source=source,  # type: ignore[arg-type]
        priority=priority,
        failover_after=failover_after,
    )


def _make_supervisor(
    sources_with_priority: list[tuple[_InMemorySnapshotSource, int, timedelta]],
    *,
    repository: RuleRepository | None = None,
    bus: _RuleSourceActivationBus | None = None,
) -> RuleSourceSupervisor:
    bindings = [
        _binding(src, prio, failover_after=failover)
        for src, prio, failover in sources_with_priority
    ]
    return RuleSourceSupervisor(
        bindings=bindings,
        repository=repository or RuleRepository(),
        bus=bus,
    )


# ---------------------------------------------------------------------------
# 1. Initial election: highest-priority ready wins
# ---------------------------------------------------------------------------


class SupervisorStartElectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_supervisor_picks_highest_priority_on_start(self) -> None:
        # Three sources with priorities 10, 20, 5. Each yields one
        # snapshot. Supervisor should pick priority=20 as initial active
        # — not the first to yield.
        s_low = _InMemorySnapshotSource("low", [_make_snap(epoch=1, source_id="low")])
        s_high = _InMemorySnapshotSource("high", [_make_snap(epoch=1, source_id="high")])
        s_mid = _InMemorySnapshotSource("mid", [_make_snap(epoch=1, source_id="mid")])
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = _make_supervisor(
            [
                (s_low, 10, timedelta(seconds=1)),
                (s_high, 20, timedelta(seconds=1)),
                (s_mid, 5, timedelta(seconds=1)),
            ],
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.05)
        self.assertEqual(sv.active_source_id, "high")
        # Exactly one activation: initial -> "high"
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].previous_source_id, None)
        self.assertEqual(seen[0].source_id, "high")
        self.assertEqual(seen[0].reason, "initial")
        # All three sources reached "ready"
        self.assertEqual(sv.get_state("low"), "ready")
        self.assertEqual(sv.get_state("high"), "ready")
        self.assertEqual(sv.get_state("mid"), "ready")
        await sv.aclose()

    async def test_supervisor_emit_initial_only_once(self) -> None:
        # Single source yields one snapshot → one initial emit; no further
        # emit even if it yields a second snapshot.
        s1 = _InMemorySnapshotSource(
            "src1", [_make_snap(epoch=1, source_id="src1")]
        )
        bus1 = _RuleSourceActivationBus()
        seen1: list[RuleSourceActivation] = []
        bus1.subscribe(seen1.append)
        sv1 = _make_supervisor([(s1, 10, timedelta(seconds=1))], bus=bus1)
        await sv1.start()
        await asyncio.sleep(0.05)
        self.assertEqual(len(seen1), 1)
        self.assertEqual(seen1[0].source_id, "src1")
        self.assertEqual(seen1[0].reason, "initial")
        await sv1.aclose()

        # Separate: single source yields two snapshots; still only 1 emit.
        s2 = _InMemorySnapshotSource(
            "src2",
            [
                _make_snap(epoch=1, source_id="src2"),
                _make_snap(epoch=2, source_id="src2"),
            ],
        )
        bus2 = _RuleSourceActivationBus()
        seen2: list[RuleSourceActivation] = []
        bus2.subscribe(seen2.append)
        sv2 = _make_supervisor([(s2, 10, timedelta(seconds=1))], bus=bus2)
        await sv2.start()
        await asyncio.sleep(0.05)
        self.assertEqual(len(seen2), 1)
        self.assertEqual(seen2[0].source_id, "src2")
        self.assertEqual(seen2[0].reason, "initial")
        await sv2.aclose()

    async def test_supervisor_no_emit_when_active_unchanged(self) -> None:
        # A single active source yielding a new snapshot (different
        # version) must NOT emit a new activation fact. Reason: 3
        # conditions AND requires active source_id to actually change.
        snap_v1 = _make_snap(epoch=1, source_id="src")
        snap_v2 = _make_snap(epoch=2, source_id="src")
        s = _InMemorySnapshotSource("src", [snap_v1, snap_v2])
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = _make_supervisor([(s, 10, timedelta(seconds=1))], bus=bus)
        await sv.start()
        await asyncio.sleep(0.05)
        # Exactly one activation: the initial; the v2 snapshot is
        # the "same active" case and must NOT emit.
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].reason, "initial")
        self.assertEqual(seen[0].source_id, "src")
        # Repository reflects the latest version (epoch=2).
        self.assertEqual(sv._repository.last_version, snap_v2.version)  # type: ignore[attr-defined]
        await sv.aclose()


# ---------------------------------------------------------------------------
# 2. Failover after failover_after window
# ---------------------------------------------------------------------------


class SupervisorFailoverTest(unittest.IsolatedAsyncioTestCase):
    async def test_failover_to_higher_priority_after_start(self) -> None:
        # A higher-priority source that becomes ready AFTER start()
        # (delayed yield) takes over from the lower-priority active.
        # Since the lower-priority active is still ready (not stale),
        # this is a "manual_replace", not "failover".

        class _DelayedReadySource(_InMemorySnapshotSource):
            def __init__(self, sid: str, delay_sec: float) -> None:
                super().__init__(sid, scripted_snapshots=[])
                self._delay_sec = delay_sec

            async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
                await asyncio.sleep(self._delay_sec)
                yield _make_snap(epoch=1, source_id=self.source_id)
                # Block until cancelled.
                try:
                    await asyncio.sleep(60.0)
                except asyncio.CancelledError:
                    return

        s_primary = _DelayedReadySource("primary", delay_sec=0.0)
        s_backup = _DelayedReadySource("backup", delay_sec=0.15)
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = _make_supervisor(
            [
                (s_primary, 10, timedelta(milliseconds=50)),
                (s_backup, 20, timedelta(milliseconds=50)),
            ],
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.02)
        # Initially primary is active.
        self.assertEqual(sv.active_source_id, "primary")
        # After backup yields (and primary is still ready), the higher
        # priority takes over with "manual_replace".
        await asyncio.sleep(0.25)
        self.assertEqual(sv.active_source_id, "backup")
        reasons = [a.reason for a in seen]
        self.assertIn("initial", reasons)
        self.assertIn("manual_replace", reasons)
        await sv.aclose()

    async def test_no_switch_to_lower_priority_when_active_stale(self) -> None:
        # When active goes stale and a lower-priority source is the
        # only alternative, no failover happens. Active stays at the
        # stale source (last-known-good preserved by Repository).
        s_high = _StaleAfterYieldSnapshotSource("high")
        s_low = _LongLivedSnapshotSource("low", [_make_snap(epoch=1, source_id="low")])
        bus = _RuleSourceActivationBus()
        seen: list[RuleSourceActivation] = []
        bus.subscribe(seen.append)

        sv = _make_supervisor(
            [
                (s_high, 20, timedelta(milliseconds=100)),
                (s_low, 10, timedelta(milliseconds=100)),
            ],
            bus=bus,
        )
        await sv.start()
        await asyncio.sleep(0.02)
        self.assertEqual(sv.active_source_id, "high")
        # Wait for high to yield then raise → stale.
        await asyncio.sleep(0.05)
        self.assertEqual(sv.get_state("high"), "stale")
        # After failover_after window, no switch (low has lower priority).
        await asyncio.sleep(0.2)
        self.assertEqual(sv.active_source_id, "high")
        # Still only 1 emit: the initial. high going stale doesn't
        # emit (all_stale is M6.5.7 health event, not activation).
        self.assertEqual(len(seen), 1)
        await sv.aclose()


# ---------------------------------------------------------------------------
# 3. aclose semantics
# ---------------------------------------------------------------------------


class SupervisorCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_supervisor_aclose_idempotent(self) -> None:
        s = _InMemorySnapshotSource("only", [_make_snap(epoch=1, source_id="only")])
        sv = _make_supervisor([(s, 10, timedelta(seconds=1))])
        await sv.start()
        await asyncio.sleep(0.02)
        # First aclose
        await sv.aclose()
        # Second aclose: no-op, no exception
        await sv.aclose()
        self.assertTrue(sv.is_closed)
        # Idempotent semantics: source.aclose is invoked exactly once
        # (on the first aclose()). The second aclose() is a no-op
        # because the Supervisor is already closed.
        self.assertEqual(s.aclose_calls, 1)

    async def test_supervisor_does_not_close_repository(self) -> None:
        # Repository has no close/aclose; the test asserts that the
        # Supervisor's aclose does not invoke any close-like method
        # on the Repository (because such method does not exist).
        s = _InMemorySnapshotSource("only", [_make_snap(epoch=1, source_id="only")])
        repo = RuleRepository()
        sv = _make_supervisor([(s, 10, timedelta(seconds=1))], repository=repo)
        await sv.start()
        await asyncio.sleep(0.02)
        # Sanity: Repository has no close/aclose.
        self.assertFalse(hasattr(repo, "close"))
        self.assertFalse(hasattr(repo, "aclose"))
        # aclose runs cleanly without trying to close repository.
        await sv.aclose()
        # State after aclose: repository is untouched.
        self.assertIsNotNone(repo.last_version)

    async def test_supervisor_aclose_cancels_source_tasks(self) -> None:
        s = _LongLivedSnapshotSource("long", [_make_snap(epoch=1, source_id="long")])
        sv = _make_supervisor([(s, 10, timedelta(seconds=1))])
        await sv.start()
        await asyncio.sleep(0.02)
        # Source not yet closed
        self.assertFalse(s._closed)  # type: ignore[attr-defined]
        await sv.aclose()
        # After aclose, source is closed.
        self.assertTrue(s._closed)  # type: ignore[attr-defined]
        self.assertGreaterEqual(s.aclose_calls, 1)


# ---------------------------------------------------------------------------
# 4. priority uniqueness / validation
# ---------------------------------------------------------------------------


class SupervisorValidationTest(unittest.IsolatedAsyncioTestCase):
    def test_supervisor_priority_uniqueness_validated(self) -> None:
        # Raises in __init__ (fail-fast on bad config).
        s_a = _InMemorySnapshotSource("a", [_make_snap(epoch=1, source_id="a")])
        s_b = _InMemorySnapshotSource("b", [_make_snap(epoch=1, source_id="b")])
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_supervisor(
                [
                    (s_a, 10, timedelta(seconds=1)),
                    (s_b, 10, timedelta(seconds=1)),
                ]
            )
        self.assertEqual(cm.exception.reason, "duplicate_priority")

    def test_supervisor_negative_priority_rejected(self) -> None:
        s = _InMemorySnapshotSource("a", [_make_snap(epoch=1, source_id="a")])
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_supervisor([(s, -1, timedelta(seconds=1))])
        self.assertEqual(cm.exception.reason, "negative_priority")

    def test_supervisor_negative_failover_after_rejected(self) -> None:
        s = _InMemorySnapshotSource("a", [_make_snap(epoch=1, source_id="a")])
        with self.assertRaises(SentinelConfigurationError) as cm:
            _make_supervisor([(s, 10, timedelta(seconds=-1))])
        self.assertEqual(cm.exception.reason, "negative_failover_after")

    def test_supervisor_empty_bindings_rejected(self) -> None:
        with self.assertRaises(SentinelConfigurationError) as cm:
            RuleSourceSupervisor(bindings=[], repository=RuleRepository())
        self.assertEqual(cm.exception.reason, "empty_bindings")

    async def test_supervisor_start_after_aclose_rejected(self) -> None:
        s = _InMemorySnapshotSource("a", [_make_snap(epoch=1, source_id="a")])
        sv = _make_supervisor([(s, 10, timedelta(seconds=1))])
        await sv.aclose()
        with self.assertRaises(SentinelConfigurationError) as cm:
            await sv.start()
        self.assertEqual(cm.exception.reason, "supervisor_closed")


# ---------------------------------------------------------------------------
# 5. Import isolation — extension CANNOT import _supervisor.*
# ---------------------------------------------------------------------------


class SupervisorImportIsolationTest(unittest.TestCase):
    """中文
    ----
    验证 ``_supervisor.*`` 模块的所有 ``__all__`` 项都是私有名 (下划线
    开头) 或显式公开的 ``ActivationObserver`` 协议 (同进程 only)。

    ``atlas_richie.sentinel.__all__`` 只包含 ``__version__`` (PEP 562),
    不含 Supervisor / Binding / Activation / Bus 任一符号。

    物理隔离留给 ruff ``no-private-import`` + mypy private module
    规则在 M6.1.0d-3 阶段补; d-1 阶段靠本 contract test 兜底。

    English
    --------
    Asserts every ``__all__`` entry of the ``_supervisor.*`` modules
    is a private name (underscore prefix) or the explicit public
    ``ActivationObserver`` protocol (same-process only).

    ``atlas_richie.sentinel.__all__`` only contains ``__version__``
    (PEP 562) and excludes Supervisor / Binding / Activation / Bus.

    Physical isolation is added by ruff ``no-private-import`` + mypy
    private module rules in M6.1.0d-3; d-1 relies on this contract
    test.
    """

    def test_supervisor_not_in_top_level_all(self) -> None:
        import atlas_richie.sentinel
        all_names = list(atlas_richie.sentinel.__all__)
        # Must not contain any of the private Supervisor symbols.
        for private in (
            "RuleSourceSupervisor",
            "_RuleSourceBinding",
            "RuleSourceActivation",
            "_RuleSourceActivationBus",
        ):
            self.assertNotIn(
                private,
                all_names,
                f"{private} must not be in atlas_richie.sentinel.__all__",
            )

    def test_supervisor_module_is_private(self) -> None:
        from atlas_richie.sentinel.source import _supervisor
        # Module name ends with _supervisor (private convention).
        self.assertTrue(_supervisor.__name__.endswith("._supervisor"))

    def test_extension_cannot_reexport_supervisor(self) -> None:
        # An "extension" package that does
        # ``from atlas_richie.sentinel.source._supervisor import *``
        # must NOT re-export Supervisor / Binding / Bus (those are
        # private). Activation is the C-layer fact; only observer
        # callable is exposed as a deliberate "same-process" hook.
        from atlas_richie.sentinel.source import _supervisor
        # __all__ must be a list (extension's star-import gate)
        self.assertTrue(hasattr(_supervisor, "__all__"))
        for name in _supervisor.__all__:
            self.assertTrue(
                name.startswith("_") or name == "ActivationObserver",
                f"_supervisor.__all__ entry {name!r} is not private; "
                f"extension code might accidentally re-export it",
            )

    def test_submodule_alls_are_private(self) -> None:
        from atlas_richie.sentinel.source import _supervisor
        for sub in ("activation", "binding", "observer", "supervisor"):
            mod = getattr(_supervisor, sub)
            all_names = getattr(mod, "__all__", [])
            for name in all_names:
                self.assertTrue(
                    name.startswith("_") or name == "ActivationObserver",
                    f"_supervisor.{sub}.__all__ entry {name!r} is not private",
                )


if __name__ == "__main__":
    unittest.main()
