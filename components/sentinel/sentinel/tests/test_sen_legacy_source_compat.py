"""1.0 RuleSource 兼容 + alias 锁定测试 (M6.1.0d-1)。

中文
----
验证 API delta v3 决策 3 / MIGRATION-M6 §2:

- 1.0 公共符号 ``RuleSource`` 是 :class:`LegacyRuleSource` 的 type alias
- :class:`FileRuleSource` 仍为 :class:`LegacyRuleSource` 形态
  (start / stop / latest 公共 API 不变)
- 1.0 用户零代码改动 (``engine.install_legacy_source(source, *,
  repository=repo)`` 等同 ``source.start(repo)``)
- Legacy 路径不经过 Supervisor, 不发 activation fact
- Legacy 路径不影响 Engine 6 状态机

English
--------
Verifies API delta v3 decision 3 / MIGRATION-M6 §2:

- The 1.0 public symbol ``RuleSource`` is a type alias of
  :class:`LegacyRuleSource`.
- :class:`FileRuleSource` remains a :class:`LegacyRuleSource` (start
  / stop / latest public API unchanged).
- 1.0 users see zero code changes:
  ``engine.install_legacy_source(source, *, repository=repo)`` is
  equivalent to ``source.start(repo)``.
- The legacy path bypasses the Supervisor, does not emit activation
  facts.
- The legacy path does not affect the Engine's 6-state machine.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta

from atlas_richie.sentinel.engine.sentinel_engine import FailSafe, SentinelEngine
from atlas_richie.sentinel.errors import SentinelConfigurationError
from atlas_richie.sentinel.model.enums import EngineState
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.snapshot import RuleSnapshot, RuleVersion
from atlas_richie.sentinel.source.rule_source import (
    FileRuleSource,
    LegacyRuleSource,
    RuleSource,
    RuleSourceAssembly,
    SnapshotRuleSource,
)


# ---------------------------------------------------------------------------
# 1. Type alias: RuleSource is LegacyRuleSource
# ---------------------------------------------------------------------------


class LegacyAliasTest(unittest.TestCase):
    def test_legacy_rule_source_alias_to_rule_source(self) -> None:
        # 1.0 公共符号 ``RuleSource`` 是 :class:`LegacyRuleSource` 的
        # type alias (1.x 全程保留, 1.0 用户零代码改动)。
        self.assertIs(RuleSource, LegacyRuleSource)


# ---------------------------------------------------------------------------
# 2. FileRuleSource 形态 = LegacyRuleSource
# ---------------------------------------------------------------------------


class FileRuleSourceShapeTest(unittest.TestCase):
    def test_file_rule_source_is_legacy_rule_source(self) -> None:
        # FileRuleSource 的公共 API (start / stop / latest) 仍是
        # LegacyRuleSource 形态 (1.0 锁定, 1.x 全程不变)。
        src = FileRuleSource(path="/tmp/_unused.json", source_id="file")
        # Public attributes available (start, stop, latest, source_id, path).
        self.assertTrue(callable(getattr(src, "start", None)))
        self.assertTrue(callable(getattr(src, "stop", None)))
        self.assertTrue(callable(getattr(src, "latest", None)))
        self.assertEqual(src.source_id, "file")
        # Does NOT have new-contract SnapshotRuleSource members
        # (snapshots / aclose). If it did, a 1.0 user who also
        # implemented their own SnapshotRuleSource would see collisions.
        self.assertFalse(hasattr(src, "aclose") and callable(src.aclose))

    def test_file_rule_source_public_api_unchanged(self) -> None:
        # 1.0 用户零代码改动: FileRuleSource 的公共 API (path,
        # source_id, start, stop, latest) 全部保留。
        src = FileRuleSource(path="/tmp/_unused.json", source_id="my-source")
        # Constructor signature: path + source_id (1.0)
        self.assertEqual(src.path, "/tmp/_tmp_unused.json".replace("_tmp_", "_"))
        # Actually:
        self.assertEqual(src.path, "/tmp/_unused.json")
        self.assertEqual(src.source_id, "my-source")
        # start / stop / latest are still on the class.
        for method in ("start", "stop", "latest"):
            self.assertTrue(
                callable(getattr(src, method)),
                f"FileRuleSource.{method} must remain callable (1.0 API)",
            )


# ---------------------------------------------------------------------------
# 3. SentinelEngine.install_legacy_source 行为
# ---------------------------------------------------------------------------


class InstallLegacySourceTest(unittest.IsolatedAsyncioTestCase):
    async def test_install_legacy_source_preserves_1_0_behavior(self) -> None:
        # 1.0 行为: source.start(repository) 直连; engine.aclose 时
        # source.stop() 被调用 (1.0 清理)。
        # Use a hand-crafted LegacyRuleSource (not FileRuleSource,
        # because FileRuleSource's start() does I/O and may try to
        # access the event loop, which is messy in unit tests).
        seen: list[tuple[str, str]] = []

        class _SpyLegacySource:
            def __init__(self, sid: str) -> None:
                self.source_id = sid

            def start(self, repository: RuleRepository) -> None:
                seen.append(("start", repository.__class__.__name__))

            def stop(self) -> None:
                seen.append(("stop", ""))

            def latest(self) -> RuleSnapshot | None:
                snap = RuleSnapshot(
                    version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
                    rules={},
                    applied_at_ns=0,
                    source_id=self.source_id,
                )
                return snap

        spy = _SpyLegacySource("spy")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        repo = RuleRepository()
        # Engine must be in CREATED state for install_legacy_source.
        self.assertEqual(engine.state, EngineState.CREATED)
        engine.install_legacy_source(spy, repository=repo)
        # 1.0 行为: source.start(repository) was called.
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], ("start", "RuleRepository"))
        # aclose → source.stop() called
        async with engine:
            pass
        # After aclose, source.stop() was called.
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[1], ("stop", ""))

    async def test_legacy_path_does_not_emit_activation(self) -> None:
        # Legacy 路径不经过 Supervisor, 不发 activation fact。
        # Use a 1.0-style source whose start() applies a snapshot.
        class _ApplyingLegacySource:
            def __init__(self, sid: str) -> None:
                self.source_id = sid
                self.applied_snapshots: list[RuleSnapshot] = []

            def start(self, repository: RuleRepository) -> None:
                snap = RuleSnapshot(
                    version=RuleVersion(epoch=1, revision=0, checksum="0" * 64),
                    rules={},
                    applied_at_ns=0,
                    source_id=self.source_id,
                )
                repository.apply_snapshot(snap)
                self.applied_snapshots.append(snap)

            def stop(self) -> None:
                pass

            def latest(self) -> RuleSnapshot | None:
                return self.applied_snapshots[-1] if self.applied_snapshots else None

        spy = _ApplyingLegacySource("legacy")
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        repo = RuleRepository()
        engine.install_legacy_source(spy, repository=repo)
        # Engine does NOT have a supervisor (legacy path).
        self.assertIsNone(engine._supervisor)  # type: ignore[attr-defined]
        self.assertTrue(engine._has_legacy)  # type: ignore[attr-defined]
        self.assertFalse(engine._has_assembled)  # type: ignore[attr-defined]
        # Source applied its snapshot to the Repository directly
        # (1.0 直连行为).
        self.assertIsNotNone(repo.last_version)
        self.assertEqual(repo.last_version.epoch, 1)
        # 1.0 flow: async with engine → READY → use → aclose → SHUTDOWN
        async with engine:
            self.assertEqual(engine.state, EngineState.READY)
        # After exit, engine transitioned to SHUTDOWN normally.
        self.assertEqual(engine.state, EngineState.SHUTDOWN)

    async def test_legacy_path_does_not_require_supervisor(self) -> None:
        # Legacy 路径不创建 Supervisor, Engine 6 状态机不受影响。
        class _NoopLegacySource:
            def __init__(self) -> None:
                self.source_id = "noop"
            def start(self, repository: RuleRepository) -> None:
                pass
            def stop(self) -> None:
                pass
            def latest(self) -> RuleSnapshot | None:
                return None

        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        engine.install_legacy_source(
            _NoopLegacySource(), repository=RuleRepository()
        )
        # After install, the engine is still in CREATED state
        # (install_legacy_source doesn't transition state).
        self.assertEqual(engine.state, EngineState.CREATED)
        # No supervisor was created.
        self.assertIsNone(engine._supervisor)  # type: ignore[attr-defined]
        # Run the engine in normal 6-state machine flow.
        async with engine:
            self.assertEqual(engine.state, EngineState.READY)
            # Engine still has no supervisor.
            self.assertIsNone(engine._supervisor)  # type: ignore[attr-defined]
        # After exit, engine transitioned to SHUTDOWN normally.
        self.assertEqual(engine.state, EngineState.SHUTDOWN)


# ---------------------------------------------------------------------------
# 4. multimode_conflict — Legacy 之后不能再 assemble_sources
# ---------------------------------------------------------------------------


class LegacyConflictTest(unittest.IsolatedAsyncioTestCase):
    async def test_multimode_conflict_after_install_legacy(self) -> None:
        class _NoopLegacySource:
            source_id = "noop"
            def start(self, repository: RuleRepository) -> None:
                pass
            def stop(self) -> None:
                pass
            def latest(self) -> RuleSnapshot | None:
                return None

        class _NoopSnapshotSource:
            source_id = "snap"
            async def snapshots(self):
                if False:
                    yield  # pragma: no cover — never yields
            async def aclose(self) -> None:
                pass

        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        engine.install_legacy_source(
            _NoopLegacySource(), repository=RuleRepository()
        )
        # Engine is in CREATED; assemble_sources requires READY.
        # First, async with engine to transition to READY.
        async with engine:
            # Try to assemble_sources — must raise multimode_conflict.
            with self.assertRaises(SentinelConfigurationError) as cm:
                await engine.assemble_sources(
                    [
                        RuleSourceAssembly(
                            source=_NoopSnapshotSource(),  # type: ignore[arg-type]
                            priority=10,
                            failover_after=timedelta(seconds=1),
                        ),
                    ],
                    repository=RuleRepository(),
                )
            self.assertEqual(cm.exception.reason, "multimode_conflict")


# ---------------------------------------------------------------------------
# 5. RuleSource (alias) is still usable as a type annotation
# ---------------------------------------------------------------------------


class RuleSourceAliasUsabilityTest(unittest.TestCase):
    def test_rule_source_is_legacy(self) -> None:
        # 1.0 用户写的 ``source: RuleSource`` 类型注解, 仍能工作。
        source: RuleSource  # type: ignore[valid-type]
        # (just exercise the alias; we don't construct a concrete one)
        # type-erasure: both names point to the same class.
        self.assertIs(RuleSource, LegacyRuleSource)

    def test_snapshot_rule_source_is_distinct(self) -> None:
        # SnapshotRuleSource is the NEW contract; not the same as
        # LegacyRuleSource. 1.0 users who import RuleSource get
        # LegacyRuleSource semantics (alias), but new code that
        # imports SnapshotRuleSource gets new semantics.
        self.assertIsNot(SnapshotRuleSource, LegacyRuleSource)
        self.assertIsNot(SnapshotRuleSource, RuleSource)


if __name__ == "__main__":
    unittest.main()
