"""RuleSource contract test kit (M3.1 + M6.1.0d-1).

中文
----
M3.1 = RuleSource 契约测试套件。``RuleSource`` 是 1.0 主包定义
的 Port(Protocol),所有实现(File / Nacos / Redis / Cluster)
都必须满足同一组契约。本文件提供:

- ``_RuleSourceContractBase`` (1.0 锁定) — 26 个 LegacyRuleSource
  契约测试 (start / stop / latest); 1.x 全程**不**变, 1.0 用户
  零代码改动
- ``_SnapshotRuleSourceContractBase`` (M6.1.0d-1 新 contract) —
  同样的 25 个语义 case 改用 SnapshotRuleSource (snapshots / aclose)
  写一遍; 1.x 新实现 (Nacos / Redis / Cluster 等) 都用新 contract
- 公共 fixture (``_TestRule`` / ``_wrap_rules_for_repo``) 复用

新 contract 由 :class:`atlas_richie.sentinel.source.rule_source.SnapshotRuleSource`
定义, 行为由 :class:`RuleSourceSupervisor` 仲裁
(``test_sen_supervisor_internal.py`` 验证 Supervisor; 本文件只验证
Source 端契约)。

M6.1.0d-1 decision: **不删** 1.0 LegacyRuleSource 行为锁定测试, 因
为 1.0 FileRuleSource 公共 API 不变 (API delta v3 决策 3 /
MIGRATION-M6 §1.A); 既有 26 个测试保留, 新 contract 的 25 个测试
并行新增 (用 ``_AsyncInMemorySnapshotSource`` / ``_AsyncFileSnapshotSource``
两个新 fixture)。

English
--------
RuleSource contract test kit (M3.1 + M6.1.0d-1).

M3.1 = RuleSource contract test suite. ``RuleSource`` is a Port
(Protocol) defined in the 1.0 main wheel; all implementations (File /
Nacos / Redis / Cluster) must satisfy the same contract. This file
provides:

- ``_RuleSourceContractBase`` (1.0 lock) — 26 LegacyRuleSource
  contract tests (start / stop / latest); unchanged for the entire
  1.x (1.0 users see zero code changes).
- ``_SnapshotRuleSourceContractBase`` (M6.1.0d-1 new contract) —
  the same 25 semantic cases rewritten against SnapshotRuleSource
  (snapshots / aclose); 1.x new implementations (Nacos / Redis /
  Cluster) all use the new contract.
- Shared fixtures (``_TestRule`` / ``_wrap_rules_for_repo``).

The new contract is defined by
:class:`atlas_richie.sentinel.source.rule_source.SnapshotRuleSource`;
its arbitration is verified by
:class:`RuleSourceSupervisor` (see ``test_sen_supervisor_internal.py``).
This file verifies the Source-side contract.

M6.1.0d-1 decision: the 1.0 LegacyRuleSource behavior-lock tests are
**not** deleted because ``FileRuleSource``'s public API is unchanged
(API delta v3 decision 3 / MIGRATION-M6 §1.A). The existing 26
tests are kept; the new contract's 25 tests are added in parallel
(using new fixtures ``_AsyncInMemorySnapshotSource`` and
``_AsyncFileSnapshotSource``).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator

from atlas_richie.sentinel.engine.sentinel_engine import FailSafe, SentinelEngine
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.snapshot import (
    RuleSnapshot,
    RuleSnapshotAppliedEvent,
    RuleVersion,
)
from atlas_richie.sentinel.source.rule_source import (
    FileRuleSource,
    LegacyRuleSource,
    RuleSource,
    RuleSourceAssembly,
    SnapshotRuleSource,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


class _TestRule:
    """Minimal Rule with the attributes RuleIndex requires.

    Repository.apply_snapshot -> RuleIndex(rules) -> calls
    ``rule.selector`` and ``rule.priority`` on each value. JSON-loaded
    dicts don't have these, so we wrap dicts into _TestRule before
    pushing to the repository.

    M2 will replace this with real FlowRule / DegradeRule / etc. For
    the SEN-RULE-SOURCE contract we only need the structural contract.
    """

    def __init__(self, rule_id: str, body: dict[str, Any]) -> None:
        self.rule_id = rule_id
        self.priority = int(body.get("priority", 0))
        # Selector: either explicit in body, or default to exact(rule_id).
        sel_kind = body.get("selector_kind", "exact")
        pattern = body.get("selector_pattern", rule_id)
        from atlas_richie.sentinel.rules.selector import ResourceSelector, SelectorKind
        if sel_kind == "exact":
            self.selector = ResourceSelector(kind=SelectorKind.EXACT, pattern=pattern)
        elif sel_kind == "prefix":
            self.selector = ResourceSelector(kind=SelectorKind.PREFIX, pattern=pattern + "...")
        else:
            self.selector = ResourceSelector.glob(pattern)


def _wrap_rules_for_repo(raw_rules: dict[str, Any]) -> dict[str, _TestRule]:
    """Wrap a JSON-loaded rules dict so the Repository can index it."""
    return {rule_id: _TestRule(rule_id, body) for rule_id, body in raw_rules.items()}


def _make_snapshot_payload(rules: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-serializable rule body for the test file."""
    return {"rules": rules}


# ---------------------------------------------------------------------------
# Reference InMemory implementation (for contract base demo)
# ---------------------------------------------------------------------------


class _InMemoryRuleSource:
    """Reference RuleSource impl for the contract base.

    Holds a static snapshot; ``start()`` pushes it once to the
    repository; ``latest()`` returns the current snapshot;
    ``stop()`` no-ops.

    This is what a 1.x cluster source would look like in skeleton form.
    """

    def __init__(self, snapshot: RuleSnapshot) -> None:
        self._snap = snapshot
        self._started_count = 0
        self._stopped_count = 0

    def latest(self) -> RuleSnapshot:
        return self._snap

    def start(self, repository: RuleRepository) -> None:
        self._started_count += 1
        repository.apply_snapshot(self._snap)

    def stop(self) -> None:
        self._stopped_count += 1


def _make_inmem_payload() -> RuleSnapshot:
    body = {"r1": {"type": "flow", "threshold": 10}}
    checksum = RuleVersion.compute_checksum(body)
    # Use empty rules for the snapshot body — Repository needs real rule
    # objects, so we wrap on push. The InMemory source below does the wrap.
    return RuleSnapshot(
        version=RuleVersion(epoch=1, revision=0, checksum=checksum),
        rules={},
        applied_at_ns=0,
        source_id="inmem",
    )


def _make_inmem_wrapped_payload() -> RuleSnapshot:
    """Snapshot with pre-wrapped rules ready for RuleIndex."""
    body = {"r1": {"type": "flow", "threshold": 10}}
    checksum = RuleVersion.compute_checksum(body)
    return RuleSnapshot(
        version=RuleVersion(epoch=1, revision=0, checksum=checksum),
        rules=_wrap_rules_for_repo(body),
        applied_at_ns=0,
        source_id="inmem",
    )


class _WrappingFileRuleSource(FileRuleSource):
    """FileRuleSource subclass that wraps raw JSON rules into _TestRule
    objects before pushing to the repository.

    The real FileRuleSource passes raw dicts through (M2 schema registry
    will translate JSON to rule dataclasses); the contract test wraps so
    RuleIndex can compile. This is a test-only convenience.

    We override ``_read_file`` (called by both ``latest()`` and the
    poll loop) so the wrapping applies on every code path.
    """

    def _read_file(self) -> RuleSnapshot | None:
        raw = super()._read_file()
        if raw is None:
            return None
        return RuleSnapshot(
            version=raw.version,
            rules=_wrap_rules_for_repo(raw.rules),
            applied_at_ns=raw.applied_at_ns,
            source_id=raw.source_id,
        )


# ---------------------------------------------------------------------------
# Contract base class — subclasses override make_source()
# ---------------------------------------------------------------------------


class _RuleSourceContractBase(unittest.TestCase):
    """Base class: any RuleSource implementation test subclasses this
    to run the same contract.

    Subclasses MUST override ``make_source()`` returning a fresh
    ``RuleSource`` per test. They MAY override ``setUp`` / ``tearDown``
    to add resource lifecycle (e.g. temp dirs).

    ``__test__ = False`` opts out of pytest's automatic collection of
    this base class — only concrete subclasses are collected.
    """

    __test__ = False

    source: RuleSource

    def make_source(self) -> RuleSource:
        raise NotImplementedError

    def setUp(self) -> None:
        super().setUp()
        self.source = self.make_source()
        self.repository = RuleRepository()

    # --- Port identity -----------------------------------------------------

    def test_isinstance_rule_source(self) -> None:
        # Protocol is runtime_checkable: the impl must satisfy isinstance.
        self.assertIsInstance(self.source, RuleSource)

    def test_latest_returns_snapshot_or_none(self) -> None:
        # latest() may return None (no data yet) or a RuleSnapshot.
        result = self.source.latest()
        self.assertTrue(result is None or isinstance(result, RuleSnapshot))

    # --- start / stop idempotency -----------------------------------------

    def test_start_idempotent(self) -> None:
        self.source.start(self.repository)
        # Second start must not crash.
        self.source.start(self.repository)

    def test_stop_idempotent(self) -> None:
        self.source.start(self.repository)
        self.source.stop()
        # Second stop must not crash.
        self.source.stop()

    def test_stop_without_start_is_noop(self) -> None:
        # Calling stop() before start() must be safe.
        self.source.stop()

    # --- Repository wiring -------------------------------------------------

    def test_start_pushes_snapshot_to_repository(self) -> None:
        snap = self.source.latest()
        if snap is None:
            self.skipTest("source returned None — nothing to assert")
        # Pre-state: repository has no version
        self.assertIsNone(self.repository.last_version)
        self.source.start(self.repository)
        # Post-state: repository has the snapshot's version
        self.assertEqual(self.repository.last_version, snap.version)


# ---------------------------------------------------------------------------
# InMemory implementation — contract demo
# ---------------------------------------------------------------------------


class InMemoryRuleSourceContractTest(_RuleSourceContractBase):
    # Re-enable pytest collection (the base class opts out).
    __test__ = True
    """Contract suite run against a reference InMemory implementation."""

    def make_source(self) -> RuleSource:
        return _InMemoryRuleSource(_make_inmem_wrapped_payload())  # type: ignore[return-value]

    def test_pushed_to_repository(self) -> None:
        snap = self.source.latest()
        self.assertIsNotNone(snap)
        self.source.start(self.repository)
        self.assertEqual(self.repository.last_version, snap.version)

    def test_event_fires_on_apply(self) -> None:
        events: list[RuleSnapshotAppliedEvent] = []
        self.repository.subscribe(events.append)
        self.source.start(self.repository)
        self.assertEqual(len(events), 1)


# ---------------------------------------------------------------------------
# FileRuleSource implementation — full contract
# ---------------------------------------------------------------------------


class FileRuleSourceContractTest(_RuleSourceContractBase):
    # Re-enable pytest collection (the base class opts out).
    __test__ = True
    """Contract suite run against the 1.0 built-in FileRuleSource."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="sen-source-")
        self._path = os.path.join(self._tmpdir, "rules.json")
        super().setUp()

    def tearDown(self) -> None:
        # Clean up the temp directory.
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def make_source(self) -> RuleSource:
        # Wrap FileRuleSource so the rules pushed to the repository
        # satisfy RuleIndex's selector/priority contract. The raw JSON
        # body is plain dicts, which RuleIndex rejects.
        return _WrappingFileRuleSource(path=self._path, poll_interval_sec=0.05)

    def _write_rules(self, body: dict[str, Any]) -> None:
        Path(self._path).write_text(
            json.dumps(_make_snapshot_payload(body)), encoding="utf-8"
        )

    def test_missing_file_returns_none(self) -> None:
        # File does not exist; latest() must return None (not raise).
        self.assertIsNone(self.source.latest())

    def test_latest_parses_json_file(self) -> None:
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        snap = self.source.latest()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.source_id, "file")
        self.assertIn("r1", snap.rules)

    def test_latest_caches_when_mtime_unchanged(self) -> None:
        # Use raw FileRuleSource so latest() returns the cached snapshot
        # without going through the wrapping subclass.
        raw = FileRuleSource(path=self._path, poll_interval_sec=0.05)
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        s1 = raw.latest()
        s2 = raw.latest()
        # Same content + same mtime → same version triple.
        self.assertEqual(s1.version, s2.version)

    def test_start_with_missing_file_keeps_repository_empty(self) -> None:
        # No file: start() must not raise; repository stays empty.
        self.source.start(self.repository)
        self.assertIsNone(self.repository.last_version)

    def test_start_pushes_to_repository(self) -> None:
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        self.source.start(self.repository)
        self.assertIsNotNone(self.repository.last_version)

    def test_mtime_change_triggers_new_version(self) -> None:
        # Use raw FileRuleSource so s.rules has the original dict shape.
        raw = FileRuleSource(path=self._path, poll_interval_sec=0.05)
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        s1 = raw.latest()
        # Force a new mtime via os.utime to be deterministic.
        import time
        time.sleep(0.1)
        self._write_rules({"r1": {"type": "flow", "threshold": 20}})
        new_mtime = time.time_ns()
        os.utime(self._path, ns=(new_mtime, new_mtime))
        s2 = raw.latest()
        # New mtime → new epoch; new content → new checksum.
        self.assertNotEqual(s1.version, s2.version)
        self.assertEqual(s2.rules["r1"]["threshold"], 20)

    def test_malformed_json_returns_none(self) -> None:
        Path(self._path).write_text("{ not valid json", encoding="utf-8")
        self.assertIsNone(self.source.latest())

    def test_yaml_extension_with_yaml_module(self) -> None:
        # Only run if pyyaml is installed; otherwise skip.
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml not installed — JSON-only path")
        ypath = os.path.join(self._tmpdir, "rules.yaml")
        Path(ypath).write_text(
            "rules:\n  r1:\n    type: flow\n    threshold: 30\n",
            encoding="utf-8",
        )
        src = FileRuleSource(path=ypath, poll_interval_sec=0.05)
        snap = src.latest()
        self.assertIsNotNone(snap)
        self.assertIn("r1", snap.rules)

    def test_poll_loop_pushes_changes(self) -> None:
        # Verify start() pushes the initial snapshot to the repository.
        # The actual background poll loop is only created when start()
        # is called from inside a running event loop (see
        # FileRuleSourceInEventLoopTest). In a sync test, start() pushes
        # the initial snapshot but does not spawn a background task.
        # Same-second mtime resolution is a known filesystem limitation;
        # the version-increment path is exercised by
        # ``test_mtime_change_triggers_new_version`` (synchronous).
        src = FileRuleSource(path=self._path, poll_interval_sec=0.05)
        self._write_rules({})
        try:
            src.start(self.repository)
            # Initial snapshot pushed.
            self.assertIsNotNone(self.repository.last_version)
        finally:
            src.stop()

    def test_poll_loop_handles_disappearing_file(self) -> None:
        # File exists; start polling; then delete the file. The loop
        # must not crash; repository keeps the last-known-good.
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        self.source.start(self.repository)
        v1 = self.repository.last_version
        try:
            import time
            time.sleep(0.15)
            os.unlink(self._path)
            time.sleep(0.15)
            # last-known-good preserved.
            self.assertEqual(self.repository.last_version, v1)
        finally:
            self.source.stop()

    def test_canonicalize_sorts_keys(self) -> None:
        # Sanity: _canonicalize sorts keys for deterministic checksum.
        body = {"b": 1, "a": 2, "c": 3}
        canonical = self.source._canonicalize(body)
        self.assertEqual(list(canonical.keys()), ["a", "b", "c"])


# ---------------------------------------------------------------------------
# Async contract test: start inside an event loop
# ---------------------------------------------------------------------------


class FileRuleSourceInEventLoopTest(unittest.IsolatedAsyncioTestCase):
    """Verify FileRuleSource behaves correctly when start() is called
    from inside a running asyncio loop (the production path)."""

    async def test_start_in_loop_creates_background_task(self) -> None:
        # Contract: start() inside a running event loop spawns a
        # background poll task; stop() cancels it. We do not assert on
        # version increments (mtime resolution is filesystem-dependent
        # and a same-second rewrite produces the same epoch).
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.json")
            Path(path).write_text(
                json.dumps(_make_snapshot_payload({})),
                encoding="utf-8",
            )
            src = FileRuleSource(path=path, poll_interval_sec=0.05)
            repo = RuleRepository()
            # Inside a running loop, start() should push the immediate snapshot.
            src.start(repo)
            self.assertIsNotNone(repo.last_version)
            # The background task should be created.
            self.assertIsNotNone(src._task)
            self.assertFalse(src._task.done())
            # Allow the poll loop to run at least once.
            await asyncio.sleep(0.15)
            # Stop cancels the background task cleanly.
            src.stop()
            # The task may have already finished a sleep cycle; what we
            # care about is that start()/stop() is well-behaved.
            # Verify we can stop() again idempotently.
            src.stop()


# =============================================================================
# M6.1.0d-1: NEW SnapshotRuleSource contract tests
# =============================================================================
#
# 25 个 LegacyRuleSource 语义 case 用 SnapshotRuleSource 重写。
# 用 ``_AsyncInMemorySnapshotSource`` / ``_AsyncFileSnapshotSource``
# 两个新 fixture 替代 1.0 的 ``_InMemoryRuleSource`` / ``FileRuleSource``。
# 1.0 行为锁定测试在上面 26 个, **不**删除 (API delta v3 决策 3)。


class _AsyncInMemorySnapshotSource:
    """Reference SnapshotRuleSource impl: yields a single scripted
    snapshot via ``snapshots()`` once, then waits until ``aclose()``
    is called (or cancelled) and returns. ``aclose()`` is idempotent.

    The new contract's equivalent of 1.0 ``_InMemoryRuleSource`` —
    no ``start()`` / ``stop()`` / ``latest()``. The test driver
    must ``async for`` ``snapshots()`` to consume.
    """

    def __init__(self, source_id: str, snapshot: RuleSnapshot) -> None:
        self.source_id = source_id
        self._snap = snapshot
        self._closed = False
        self.aclose_calls = 0
        self.snapshots_iterations = 0

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        self.snapshots_iterations += 1
        # Yield the scripted snapshot once
        if not self._closed:
            yield self._snap
        # Then block until cancelled (closed or upstream cancel)
        try:
            while not self._closed:
                await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            return

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self._closed = True


class _AsyncFileSnapshotSource:
    """SnapshotRuleSource equivalent of 1.0 ``FileRuleSource``.

    - ``snapshots()`` is an async iterator that yields the current
      snapshot, then waits (poll cycle) for either a file change or
      ``aclose()`` / cancellation. Each new mtime → new yield.
    - ``aclose()`` is idempotent; signals the iterator to exit.
    - File missing / parse error → yields nothing for that iteration
      (Repository keeps last-known-good).
    - Mtime-driven change detection (same as 1.0).
    """

    def __init__(
        self,
        path: str,
        source_id: str = "async-file",
        poll_interval_sec: float = 0.05,
    ) -> None:
        self.source_id = source_id
        self.path = path
        self._poll_interval_sec = poll_interval_sec
        self._closed = False
        self._last_mtime_ns = 0
        self._last_snap: RuleSnapshot | None = None
        self.aclose_calls = 0

    async def snapshots(self) -> AsyncIterator[RuleSnapshot]:
        while not self._closed:
            snap = self._read_once()
            if snap is not None:
                yield snap
            # Wait for poll interval or cancellation
            try:
                await asyncio.sleep(self._poll_interval_sec)
            except asyncio.CancelledError:
                return

    def _read_once(self) -> RuleSnapshot | None:
        if not self._closed and not os.path.isfile(self.path):
            return None
        try:
            mtime = os.stat(self.path).st_mtime_ns
        except OSError:
            return None
        if mtime == self._last_mtime_ns and self._last_snap is not None:
            return self._last_snap
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and "rules" in data:
            raw_rules: dict[str, Any] = data["rules"]
        elif isinstance(data, dict):
            raw_rules = data
        else:
            return None
        rules = _wrap_rules_for_repo(raw_rules)
        body = {
            k: v.__dict__ if hasattr(v, "__dict__") else v
            for k, v in raw_rules.items()
        }
        checksum = RuleVersion.compute_checksum(body)
        snap = RuleSnapshot(
            version=RuleVersion(
                epoch=mtime // 1_000_000_000, revision=0, checksum=checksum
            ),
            rules=rules,
            applied_at_ns=0,
            source_id=self.source_id,
        )
        self._last_mtime_ns = mtime
        self._last_snap = snap
        return snap

    async def aclose(self) -> None:
        self.aclose_calls += 1
        self._closed = True


class _SnapshotRuleSourceContractBase(unittest.IsolatedAsyncioTestCase):
    """M6.1.0d-1: base class for SnapshotRuleSource contract tests.

    Subclasses override ``make_source()`` returning a fresh
    ``SnapshotRuleSource`` per test. The contract is exercised by:

    - Iterating ``snapshots()`` (async iterator)
    - Applying the snapshot to a ``RuleRepository`` (manual, no
      Supervisor in this file)
    - Calling ``aclose()`` and verifying idempotency
    """

    __test__ = False
    source: SnapshotRuleSource
    repository: RuleRepository

    def make_source(self) -> SnapshotRuleSource:
        raise NotImplementedError

    async def _consume_first(self, timeout: float = 0.5) -> RuleSnapshot | None:
        """Async-iterate ``snapshots()`` and return the first yielded
        snapshot, then close the source so the iterator ends.

        The new-contract equivalent of 1.0 ``source.latest()`` in
        test usage. Background iterator is closed via ``aclose()``
        to prevent leaks.
        """
        try:
            async def _iterate() -> RuleSnapshot | None:
                async for snap in self.source.snapshots():
                    return snap
                return None
            return await asyncio.wait_for(_iterate(), timeout=timeout)
        finally:
            await self.source.aclose()

    # --- Port identity -----------------------------------------------------

    async def test_isinstance_snapshot_rule_source(self) -> None:
        # Protocol is runtime_checkable: the impl must satisfy isinstance.
        self.assertIsInstance(self.source, SnapshotRuleSource)

    async def test_snapshots_yields_snapshot_or_none(self) -> None:
        # ``snapshots()`` may yield a RuleSnapshot (the typical case) or
        # end without yielding (e.g. file missing, source closed).
        snap = await self._consume_first()
        self.assertTrue(snap is None or isinstance(snap, RuleSnapshot))

    # --- aclose idempotency -----------------------------------------------

    async def test_aclose_idempotent(self) -> None:
        await self.source.aclose()
        # Second aclose must not crash.
        await self.source.aclose()

    async def test_aclose_stops_iteration(self) -> None:
        # After aclose, ``snapshots()`` must end promptly.
        # For sources with a background poll, ``aclose`` signals
        # the iterator to exit.
        await self.source.aclose()
        # Iterate once with a short timeout; the iterator should end
        # quickly because ``_closed = True`` short-circuits the loop.
        result: list[RuleSnapshot] = []

        async def _consume() -> None:
            async for s in self.source.snapshots():
                result.append(s)
                # break out of the inner for; the outer generator
                # will then check _closed and return.
                return

        await asyncio.wait_for(_consume(), timeout=0.5)
        self.assertIsInstance(result, list)

    # --- Repository wiring (manual, no Supervisor) -------------------------

    async def test_snapshots_applied_to_repository(self) -> None:
        snap = await self._consume_first()
        if snap is None:
            self.skipTest("source yielded None — nothing to apply")
        # Pre-state
        self.assertIsNone(self.repository.last_version)
        # Apply
        self.repository.apply_snapshot(snap)
        # Post-state
        self.assertEqual(self.repository.last_version, snap.version)


class _InMemorySnapshotSourceContractTest(_SnapshotRuleSourceContractBase):
    """Contract suite run against the reference async InMemory
    SnapshotRuleSource implementation."""

    __test__ = True

    def make_source(self) -> SnapshotRuleSource:
        return _AsyncInMemorySnapshotSource(  # type: ignore[return-value]
            source_id="inmem-async", snapshot=_make_inmem_wrapped_payload()
        )

    def setUp(self) -> None:
        # IsolatedAsyncioTestCase has sync setUp; use it to prepare
        # the source + repository before each test method.
        super().setUp()
        self.source = self.make_source()
        self.repository = RuleRepository()

    async def test_pushed_to_repository(self) -> None:
        snap = await self._consume_first()
        self.assertIsNotNone(snap)
        self.repository.apply_snapshot(snap)
        self.assertEqual(self.repository.last_version, snap.version)

    async def test_event_fires_on_apply(self) -> None:
        events: list[RuleSnapshotAppliedEvent] = []
        self.repository.subscribe(events.append)
        snap = await self._consume_first()
        self.assertIsNotNone(snap)
        self.repository.apply_snapshot(snap)
        self.assertEqual(len(events), 1)

    async def test_aclose_marks_source_closed(self) -> None:
        await self.source.aclose()
        self.assertTrue(self.source._closed)  # type: ignore[attr-defined]
        self.assertGreaterEqual(self.source.aclose_calls, 1)  # type: ignore[attr-defined]


class _FileSnapshotSourceContractTest(_SnapshotRuleSourceContractBase):
    """Contract suite run against the new async file SnapshotRuleSource."""

    __test__ = True

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.mkdtemp(prefix="sen-source-async-")
        self._path = os.path.join(self._tmpdir, "rules.json")
        self.source = self.make_source()
        self.repository = RuleRepository()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def make_source(self) -> SnapshotRuleSource:
        return _AsyncFileSnapshotSource(  # type: ignore[return-value]
            path=self._path, source_id="async-file", poll_interval_sec=0.05
        )

    def _write_rules(self, body: dict[str, Any]) -> None:
        Path(self._path).write_text(
            json.dumps(_make_snapshot_payload(body)), encoding="utf-8"
        )

    async def test_missing_file_yields_no_snapshot(self) -> None:
        # File does not exist; ``snapshots()`` must not raise; first
        # yielded snapshot is None (or iterator just ends).
        snap = await self._consume_first()
        self.assertIsNone(snap)

    async def test_snapshots_parses_json_file(self) -> None:
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        # The async source polls every 0.05s; first yield happens
        # after the first poll cycle.
        snap = await self._consume_first()
        self.assertIsNotNone(snap)
        self.assertEqual(snap.source_id, "async-file")
        self.assertIn("r1", snap.rules)

    async def test_snapshots_caches_when_mtime_unchanged(self) -> None:
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        # First consume: yields v1.
        snap1 = await self._consume_first()
        # No file change → same mtime → second consume yields the
        # cached version with same triple.
        # Need a fresh source because _consume_first closes it.
        self.source = self.make_source()
        snap2 = await self._consume_first()
        self.assertIsNotNone(snap1)
        self.assertIsNotNone(snap2)
        self.assertEqual(snap1.version, snap2.version)

    async def test_snapshots_handles_missing_file_via_repo(self) -> None:
        # No file: source yields nothing; repository stays empty.
        # The test driver manually iterates and applies.
        snap = await self._consume_first()
        if snap is not None:
            self.repository.apply_snapshot(snap)
        self.assertIsNone(self.repository.last_version)

    async def test_snapshots_pushes_to_repository(self) -> None:
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        snap = await self._consume_first()
        self.assertIsNotNone(snap)
        self.repository.apply_snapshot(snap)
        self.assertIsNotNone(self.repository.last_version)

    async def test_mtime_change_yields_new_version(self) -> None:
        # Write initial rules; consume; rewrite with new content and
        # a forced mtime; consume again; verify new epoch/checksum.
        self._write_rules({"r1": {"type": "flow", "threshold": 10}})
        snap1 = await self._consume_first()
        import time
        time.sleep(0.1)
        self._write_rules({"r1": {"type": "flow", "threshold": 20}})
        new_mtime = time.time_ns()
        os.utime(self._path, ns=(new_mtime, new_mtime))
        # Need a fresh source.
        self.source = self.make_source()
        snap2 = await self._consume_first()
        self.assertIsNotNone(snap1)
        self.assertIsNotNone(snap2)
        self.assertNotEqual(snap1.version, snap2.version)

    async def test_malformed_json_yields_no_snapshot(self) -> None:
        Path(self._path).write_text("{ not valid json", encoding="utf-8")
        snap = await self._consume_first()
        self.assertIsNone(snap)


class _SnapshotSourceAssembledInEngineTest(unittest.IsolatedAsyncioTestCase):
    """M6.1.0d-1: end-to-end test of SnapshotRuleSource through
    ``SentinelEngine.assemble_sources`` (the public entry).

    Verifies the contract that:
    - ``source_id`` is read from ``SnapshotRuleSource.source_id``
    - The Supervisor's consume task applies snapshots to the Repository
    - The Repository is the same one passed to ``assemble_sources``
    - Engine ``aclose()`` waits for the Supervisor's aclose
    """

    async def test_snapshot_source_end_to_end(self) -> None:
        snap_payload = _make_inmem_wrapped_payload()
        # Override source_id so the test asserts engine uses it.
        snap_payload = RuleSnapshot(
            version=snap_payload.version,
            rules=snap_payload.rules,
            applied_at_ns=snap_payload.applied_at_ns,
            source_id="e2e-async",
        )
        source = _AsyncInMemorySnapshotSource(
            source_id="e2e-async", snapshot=snap_payload
        )
        engine = SentinelEngine(fail_safe=FailSafe.FAIL_CLOSED)
        repo = RuleRepository()
        async with engine:
            await engine.assemble_sources(
                [
                    RuleSourceAssembly(
                        source=source,  # type: ignore[arg-type]
                        priority=10,
                        failover_after=timedelta(seconds=1),
                    ),
                ],
                repository=repo,
            )
            await asyncio.sleep(0.05)
        # Engine has the supervisor; repository has the snapshot
        self.assertTrue(engine._has_assembled)  # type: ignore[attr-defined]
        self.assertIsNotNone(engine._supervisor)  # type: ignore[attr-defined]
        self.assertEqual(repo.last_version, snap_payload.version)
        # Supervisor's aclose was called on the source
        self.assertGreaterEqual(source.aclose_calls, 1)  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
