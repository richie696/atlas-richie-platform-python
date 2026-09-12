"""SEN-RULE-001 baseline tests (M1.6).

中文
----
SEN-RULE-001 = RuleSnapshot / RuleVersion / RuleRepository / RuleIndex
基线测试,覆盖 PLANNING §M1.6 要求:

- ``RuleVersion`` 强制不变量(epoch / revision / checksum 长度)
- ``RuleVersion.compute_checksum`` 的 deterministic(同 payload 同 hash)
- ``RuleSnapshot`` 不可变 + ``MappingProxyType`` 包装
- ``RuleRepository.apply_snapshot`` 的 8 步更新:
  - 正常 apply(版本升序)→ True + 事件触发 + index 替换
  - 旧版本 → False(last-known-good 保留 + last_error 记录)
  - 同一 (epoch, revision) 不同 checksum → False(检测碰撞)
  - 重复 apply 同一版本 → True(no-op,不重复触发事件)
  - 乱序:中间版本被吞后到达的旧版本(epoch, revision 旧) → 拒绝
- ``RuleIndex.find`` 优先级排序(priority desc, rule_id asc 字典序)
- ``ResourceSelector`` 3 种 kind + 校验失败路径
- 事件订阅者抛错被 swallow(不污染业务)

不依赖 M2 规则;只用到 M1.5 公共 API。

English
--------
SEN-RULE-001 baseline tests (M1.6).

SEN-RULE-001 is the baseline test surface for RuleSnapshot / RuleVersion
/ RuleRepository / RuleIndex, covering PLANNING §M1.6:

- ``RuleVersion`` enforced invariants (epoch / revision / checksum length).
- ``RuleVersion.compute_checksum`` determinism (same payload → same hash).
- ``RuleSnapshot`` immutability + ``MappingProxyType`` wrapping.
- ``RuleRepository.apply_snapshot`` 8-step flow:
  - Normal apply (version ascending) → True + event fired + index replaced.
  - Older version → False (last-known-good kept + last_error recorded).
  - Same (epoch, revision) different checksum → False (collision detected).
  - Repeated apply of same version → True (no-op, no duplicate event).
  - Out-of-order: when an intermediate version was applied and a stale
    version arrives (epoch, revision older) → reject.
- ``RuleIndex.find`` priority sort (priority desc, rule_id asc lexicographic).
- ``ResourceSelector`` 3 kinds + validation failure paths.
- Subscriber raising is swallowed (no business pollution).

No M2 rules are required; only the M1.5 public API is used.
"""

from __future__ import annotations

import unittest
from typing import Any

from atlas_richie.sentinel.errors import RuleSnapshotError
from atlas_richie.sentinel.rules.index import RuleIndex
from atlas_richie.sentinel.rules.repository import RuleRepository
from atlas_richie.sentinel.rules.selector import (
    ResourceSelector,
    SelectorKind,
)
from atlas_richie.sentinel.rules.snapshot import (
    RuleSnapshot,
    RuleSnapshotAppliedEvent,
    RuleVersion,
)


# ---------------------------------------------------------------------------
# Test fixtures: minimal "Rule" objects that satisfy the RuleIndex contract
# ---------------------------------------------------------------------------


class _Rule:
    """A minimal Rule stand-in for tests.

    M2 will replace this with real FlowRule / DegradeRule / etc. For
    SEN-RULE-001 we only need an object that exposes ``rule_id``,
    ``priority``, and ``selector``. The dataclass contract is verified
    in M2.x; here we use a plain class.
    """

    def __init__(
        self,
        rule_id: str,
        *,
        priority: int = 0,
        selector: ResourceSelector | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.priority = priority
        self.selector = selector or ResourceSelector.exact(rule_id)


def _make_snapshot(
    version: RuleVersion,
    rules: dict[str, _Rule],
    *,
    source_id: str = "test",
) -> RuleSnapshot:
    return RuleSnapshot(
        version=version,
        rules=rules,
        applied_at_ns=0,
        source_id=source_id,
    )


# ---------------------------------------------------------------------------
# RuleVersion invariants
# ---------------------------------------------------------------------------


class RuleVersionInvariantsTest(unittest.TestCase):
    def test_negative_epoch_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuleVersion(epoch=-1, revision=0, checksum="a" * 64)

    def test_negative_revision_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuleVersion(epoch=0, revision=-1, checksum="a" * 64)

    def test_short_checksum_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuleVersion(epoch=0, revision=0, checksum="abc123")

    def test_long_checksum_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuleVersion(epoch=0, revision=0, checksum="a" * 65)

    def test_zero_zero_reserved_epoch_revision_accepted(self) -> None:
        # epoch=0 / revision=0 are "uninitialized" but not invalid.
        v = RuleVersion(epoch=0, revision=0, checksum="a" * 64)
        self.assertEqual(v.epoch, 0)
        self.assertEqual(v.revision, 0)

    def test_frozen_immutability(self) -> None:
        v = RuleVersion(epoch=1, revision=2, checksum="a" * 64)
        with self.assertRaises(Exception):
            v.epoch = 99  # type: ignore[misc]

    def test_compute_checksum_deterministic(self) -> None:
        payload = {"a": 1, "b": 2, "nested": {"x": "y"}}
        c1 = RuleVersion.compute_checksum(payload)
        c2 = RuleVersion.compute_checksum(payload)
        self.assertEqual(c1, c2)
        self.assertEqual(len(c1), 64)

    def test_compute_checksum_key_order_independent(self) -> None:
        # Same logical content, different dict insertion order → same hash.
        c1 = RuleVersion.compute_checksum({"a": 1, "b": 2})
        c2 = RuleVersion.compute_checksum({"b": 2, "a": 1})
        self.assertEqual(c1, c2)

    def test_compute_checksum_changes_with_content(self) -> None:
        c1 = RuleVersion.compute_checksum({"a": 1})
        c2 = RuleVersion.compute_checksum({"a": 2})
        self.assertNotEqual(c1, c2)

    def test_lexicographic_compare(self) -> None:
        v_a = RuleVersion(epoch=1, revision=0, checksum="a" * 64)
        v_b = RuleVersion(epoch=1, revision=1, checksum="a" * 64)
        v_c = RuleVersion(epoch=2, revision=0, checksum="a" * 64)
        self.assertLess(v_a, v_b)
        self.assertLess(v_b, v_c)
        self.assertLess(v_a, v_c)
        # Same triple
        self.assertEqual(v_a, RuleVersion(epoch=1, revision=0, checksum="a" * 64))
        # Checksum-only diff
        v_a2 = RuleVersion(epoch=1, revision=0, checksum="b" * 64)
        self.assertNotEqual(v_a, v_a2)


# ---------------------------------------------------------------------------
# RuleSnapshot immutability
# ---------------------------------------------------------------------------


class RuleSnapshotImmutabilityTest(unittest.TestCase):
    def test_rules_wrapped_in_mapping_proxy(self) -> None:
        raw = {"r1": _Rule("r1")}
        snap = _make_snapshot(
            RuleVersion(0, 0, "a" * 64),
            raw,  # type: ignore[arg-type]
        )
        # MappingProxyType — read-only at runtime.
        from types import MappingProxyType
        self.assertIsInstance(snap.rules, MappingProxyType)
        with self.assertRaises(TypeError):
            snap.rules["r2"] = _Rule("r2")  # type: ignore[index]

    def test_frozen_dataclass(self) -> None:
        snap = _make_snapshot(RuleVersion(0, 0, "a" * 64), {})
        with self.assertRaises(Exception):
            snap.applied_at_ns = 999  # type: ignore[misc]

    def test_negative_applied_at_ns_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuleSnapshot(
                version=RuleVersion(0, 0, "a" * 64),
                rules={},
                applied_at_ns=-1,
            )


# ---------------------------------------------------------------------------
# ResourceSelector
# ---------------------------------------------------------------------------


class ResourceSelectorTest(unittest.TestCase):
    def test_exact_matches(self) -> None:
        s = ResourceSelector.exact("orders-api")
        self.assertIs(s.kind, SelectorKind.EXACT)
        self.assertTrue(s.matches("orders-api"))
        self.assertFalse(s.matches("orders-api-v2"))
        self.assertFalse(s.matches("OTHER"))

    def test_prefix_matches(self) -> None:
        s = ResourceSelector.prefix("orders-")
        self.assertIs(s.kind, SelectorKind.PREFIX)
        self.assertTrue(s.matches("orders-api"))
        self.assertTrue(s.matches("orders-anything"))
        self.assertFalse(s.matches("users-api"))

    def test_glob_matches(self) -> None:
        s = ResourceSelector.glob("orders-*-v1")
        self.assertIs(s.kind, SelectorKind.GLOB)
        self.assertTrue(s.matches("orders-api-v1"))
        self.assertFalse(s.matches("orders-api-v2"))

    def test_empty_pattern_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ResourceSelector(kind=SelectorKind.EXACT, pattern="")

    def test_prefix_without_ellipsis_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ResourceSelector(kind=SelectorKind.PREFIX, pattern="orders-")

    def test_prefix_with_only_ellipsis_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ResourceSelector(kind=SelectorKind.PREFIX, pattern="...")


# ---------------------------------------------------------------------------
# RuleIndex priority sort
# ---------------------------------------------------------------------------


class RuleIndexTest(unittest.TestCase):
    def test_find_empty_index(self) -> None:
        idx = RuleIndex({})
        self.assertEqual(list(idx.find("anything")), [])

    def test_find_returns_sorted_by_priority_desc(self) -> None:
        rules = {
            "low": _Rule("low", priority=1, selector=ResourceSelector.exact("r")),
            "high": _Rule("high", priority=10, selector=ResourceSelector.exact("r")),
            "mid": _Rule("mid", priority=5, selector=ResourceSelector.exact("r")),
        }
        idx = RuleIndex(rules)  # type: ignore[arg-type]
        found = [r.rule_id for r in idx.find("r")]
        self.assertEqual(found, ["high", "mid", "low"])

    def test_find_priority_tie_breaks_on_rule_id_asc(self) -> None:
        rules = {
            "b": _Rule("b", priority=5, selector=ResourceSelector.exact("r")),
            "a": _Rule("a", priority=5, selector=ResourceSelector.exact("r")),
            "c": _Rule("c", priority=5, selector=ResourceSelector.exact("r")),
        }
        idx = RuleIndex(rules)  # type: ignore[arg-type]
        found = [r.rule_id for r in idx.find("r")]
        self.assertEqual(found, ["a", "b", "c"])

    def test_exact_match_beats_prefix_beats_glob(self) -> None:
        # Single resource; 3 rules at different selector kinds.
        # Glob `orders-*` matches `orders-api` so the glob rule should
        # appear after exact and prefix in the result.
        rules = {
            "glob": _Rule("glob", priority=10, selector=ResourceSelector.glob("orders-*")),
            "prefix": _Rule("prefix", priority=10, selector=ResourceSelector.prefix("orders-")),
            "exact": _Rule("exact", priority=10, selector=ResourceSelector.exact("orders-api")),
        }
        idx = RuleIndex(rules)  # type: ignore[arg-type]
        found = [r.rule_id for r in idx.find("orders-api")]
        self.assertEqual(found, ["exact", "prefix", "glob"])

    def test_no_match_returns_empty(self) -> None:
        rules = {
            "r1": _Rule("r1", priority=1, selector=ResourceSelector.exact("foo")),
        }
        idx = RuleIndex(rules)  # type: ignore[arg-type]
        self.assertEqual(list(idx.find("bar")), [])


# ---------------------------------------------------------------------------
# RuleRepository 8-step flow
# ---------------------------------------------------------------------------


class RuleRepositoryApplyTest(unittest.TestCase):
    def test_first_apply_succeeds(self) -> None:
        repo = RuleRepository()
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({"a": 1}))
        snap = _make_snapshot(v, {"r1": _Rule("r1")})
        self.assertTrue(repo.apply_snapshot(snap))
        self.assertEqual(repo.last_version, v)
        self.assertIsNone(repo.last_error)

    def test_apply_event_fires(self) -> None:
        repo = RuleRepository()
        events: list[RuleSnapshotAppliedEvent] = []
        repo.subscribe(events.append)
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        snap = _make_snapshot(v, {"r1": _Rule("r1")})
        repo.apply_snapshot(snap)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].version, v)
        self.assertEqual(events[0].rule_count, 1)

    def test_repeat_apply_same_version_is_noop(self) -> None:
        repo = RuleRepository()
        events: list[RuleSnapshotAppliedEvent] = []
        repo.subscribe(events.append)
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        snap = _make_snapshot(v, {"r1": _Rule("r1")})
        self.assertTrue(repo.apply_snapshot(snap))
        self.assertTrue(repo.apply_snapshot(snap))
        # Only one event — second apply is a no-op.
        self.assertEqual(len(events), 1)

    def test_newer_version_replaces(self) -> None:
        repo = RuleRepository()
        v1 = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({"v": 1}))
        v2 = RuleVersion(epoch=1, revision=1, checksum=RuleVersion.compute_checksum({"v": 2}))
        repo.apply_snapshot(_make_snapshot(v1, {"r1": _Rule("r1")}))
        self.assertTrue(repo.apply_snapshot(_make_snapshot(v2, {"r2": _Rule("r2")})))
        self.assertEqual(repo.last_version, v2)
        # Index now has r2, not r1.
        self.assertEqual(list(repo.current_index.find("r1")), [])
        self.assertEqual(len(list(repo.current_index.find("r2"))), 1)

    def test_older_version_rejected(self) -> None:
        repo = RuleRepository()
        v1 = RuleVersion(epoch=1, revision=1, checksum=RuleVersion.compute_checksum({}))
        v_old = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        repo.apply_snapshot(_make_snapshot(v1, {"r1": _Rule("r1")}))
        # Trying to apply a strictly older version (revision 0 < 1).
        self.assertFalse(repo.apply_snapshot(_make_snapshot(v_old, {"r2": _Rule("r2")})))
        self.assertIsInstance(repo.last_error, RuleSnapshotError)
        # last-known-good is preserved.
        self.assertEqual(repo.last_version, v1)

    def test_same_epoch_revision_different_checksum_rejected(self) -> None:
        repo = RuleRepository()
        c1 = "a" * 64
        c2 = "b" * 64
        v1 = RuleVersion(epoch=1, revision=0, checksum=c1)
        v2 = RuleVersion(epoch=1, revision=0, checksum=c2)
        repo.apply_snapshot(_make_snapshot(v1, {"r1": _Rule("r1")}))
        # Same (epoch, revision), different checksum — collision/bug.
        self.assertFalse(repo.apply_snapshot(_make_snapshot(v2, {"r2": _Rule("r2")})))
        self.assertIsInstance(repo.last_error, RuleSnapshotError)
        # Old version retained.
        self.assertEqual(repo.last_version, v1)

    def test_out_of_order_apply_skips_orphan(self) -> None:
        # Common scenario: source pushes v1, v3, v2 (v3 was misordered).
        # After v1 applied, v2 should be accepted. After v3 applied,
        # v2 (now older) must be rejected.
        repo = RuleRepository()
        v1 = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        v2 = RuleVersion(epoch=1, revision=1, checksum=RuleVersion.compute_checksum({}))
        v3 = RuleVersion(epoch=1, revision=2, checksum=RuleVersion.compute_checksum({}))
        repo.apply_snapshot(_make_snapshot(v1, {"r1": _Rule("r1")}))
        # v3 skips over v2.
        repo.apply_snapshot(_make_snapshot(v3, {"r3": _Rule("r3")}))
        # Now v2 arrives late — must be rejected (older than v3).
        self.assertFalse(repo.apply_snapshot(_make_snapshot(v2, {"r2": _Rule("r2")})))
        # v3 still active.
        self.assertEqual(repo.last_version, v3)

    def test_subscriber_exception_is_swallowed(self) -> None:
        repo = RuleRepository()

        def bad_sub(_event: Any) -> None:
            raise RuntimeError("subscriber boom")

        repo.subscribe(bad_sub)
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        # Must not raise.
        repo.apply_snapshot(_make_snapshot(v, {"r1": _Rule("r1")}))
        # Apply still succeeded.
        self.assertEqual(repo.last_version, v)

    def test_multiple_subscribers_all_called(self) -> None:
        repo = RuleRepository()
        a_calls: list[RuleSnapshotAppliedEvent] = []
        b_calls: list[RuleSnapshotAppliedEvent] = []
        repo.subscribe(a_calls.append)
        repo.subscribe(b_calls.append)
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        repo.apply_snapshot(_make_snapshot(v, {"r1": _Rule("r1")}))
        self.assertEqual(len(a_calls), 1)
        self.assertEqual(len(b_calls), 1)

    def test_subscriber_failure_does_not_block_others(self) -> None:
        # One subscriber raises; the next one must still be called.
        repo = RuleRepository()
        a_calls: list[Any] = []
        b_calls: list[Any] = []

        def bad(_e: Any) -> None:
            raise RuntimeError("boom")

        repo.subscribe(bad)
        repo.subscribe(a_calls.append)
        repo.subscribe(b_calls.append)
        v = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        repo.apply_snapshot(_make_snapshot(v, {"r1": _Rule("r1")}))
        self.assertEqual(len(a_calls), 1)
        self.assertEqual(len(b_calls), 1)


# ---------------------------------------------------------------------------
# Integration: Repository + Index end-to-end
# ---------------------------------------------------------------------------


class RuleRepositoryIntegrationTest(unittest.TestCase):
    def test_find_after_apply_returns_new_rules(self) -> None:
        repo = RuleRepository()
        v1 = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        rules = {
            "r1": _Rule("r1", priority=10, selector=ResourceSelector.exact("orders")),
            "r2": _Rule("r2", priority=5, selector=ResourceSelector.exact("orders")),
        }
        repo.apply_snapshot(_make_snapshot(v1, rules))  # type: ignore[arg-type]
        found = [r.rule_id for r in repo.current_index.find("orders")]
        self.assertEqual(found, ["r1", "r2"])

    def test_swap_to_new_snapshot_drops_old_rules(self) -> None:
        repo = RuleRepository()
        v1 = RuleVersion(epoch=1, revision=0, checksum=RuleVersion.compute_checksum({}))
        v2 = RuleVersion(epoch=1, revision=1, checksum=RuleVersion.compute_checksum({}))
        repo.apply_snapshot(
            _make_snapshot(v1, {"old": _Rule("old", selector=ResourceSelector.exact("r"))})
        )
        repo.apply_snapshot(
            _make_snapshot(v2, {"new": _Rule("new", selector=ResourceSelector.exact("r"))})
        )
        found = [r.rule_id for r in repo.current_index.find("r")]
        self.assertEqual(found, ["new"])


if __name__ == "__main__":
    unittest.main()
