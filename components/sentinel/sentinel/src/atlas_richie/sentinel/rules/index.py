"""Sentinel RuleIndex(M1.5)。

中文
----
``RuleIndex`` 把 ``RuleSnapshot.rules`` 编译成可查询的索引,支持
按 Resource.name O(1) 查找 + 按 selector 类型优先级排序。

匹配优先级(高 → 低):

1. ``EXACT`` — 资源名精确匹配
2. ``PREFIX`` — 前缀匹配(匹配数最少的最具体)
3. ``GLOB`` — 通配符匹配(最宽松)

同类型内:按 ``priority`` 降序(数字大 = 优先);同 priority 按
``rule_id`` 升序(字典序,确定性)。

设计要点:

- **不可变索引**:构造时一次性编译,之后只读;``RuleRepository`` 在
  atomic swap 时整体替换 RuleIndex
- **3 个内部 dict**:
  - ``_exact`` — name → [(priority, rule_id, rule), ...]
  - ``_prefix`` — 前缀 → 同上
  - ``_glob`` — glob 模式 → 同上
- **find()**:返回该 Resource 命中的所有 rule(按优先级排序),不含
  selector 拒绝的 rule

English
--------
Sentinel RuleIndex (M1.5).

``RuleIndex`` compiles ``RuleSnapshot.rules`` into a queryable index
with O(1) Resource.name lookup and selector-kind priority sort.

Match priority (high → low):

1. ``EXACT`` — exact resource name match.
2. ``PREFIX`` — prefix match (most specific wins).
3. ``GLOB`` — wildcard match (loosest).

Within a kind: sort by ``priority`` descending (larger = wins); same
priority, sort by ``rule_id`` ascending (lexicographic, deterministic).

Design points:

- **Immutable index** — built once at construction; ``RuleRepository``
  atomically swaps the whole RuleIndex on update.
- **3 internal dicts**:
  - ``_exact`` — name → [(priority, rule_id, rule), ...]
  - ``_prefix`` — prefix → same
  - ``_glob`` — glob pattern → same
- **find()** — return all matching rules for a Resource (sorted),
  excluding selector-rejected rules."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .selector import ResourceSelector, SelectorKind


@dataclass(frozen=True, slots=True)
class IndexedRule:
    """中文
    ----
    索引化的 Rule 视图(不可变)。

    - ``rule_id`` — 规则 id
    - ``priority`` — 优先级(数字大 = 优先)
    - ``selector`` — 资源选择器
    - ``rule`` — 原始 rule 对象(FlowRule / DegradeRule / ... — M2 实现)

    English
    --------
    Indexed Rule view (immutable).

    - ``rule_id`` — rule id.
    - ``priority`` — priority (larger = wins).
    - ``selector`` — resource selector.
    - ``rule`` — original rule object (FlowRule / DegradeRule / ... —
      M2 implements)."""

    rule_id: str
    priority: int
    selector: ResourceSelector
    rule: Any


class RuleIndex:
    """中文
    ----
    不可变 Rule 索引(构造时一次性编译)。

    English
    --------
    Immutable rule index (built once at construction).
    """

    __slots__ = ("_exact", "_prefix", "_glob")

    def __init__(self, rules: Mapping[str, Any] | None = None) -> None:
        # 3 个内部存储,按 selector kind 分桶
        self._exact: dict[str, list[IndexedRule]] = {}
        self._prefix: dict[str, list[IndexedRule]] = {}
        self._glob: dict[str, list[IndexedRule]] = {}
        if rules:
            for rule_id, rule in rules.items():
                self._add_rule(rule_id, rule)

    def _add_rule(self, rule_id: str, rule: Any) -> None:
        """中文
        ----
        把单个 rule 编译进对应桶。

        Rule 必须有 ``.selector`` (ResourceSelector) 和 ``.priority``
        (int) 字段;否则抛 ``ValueError``。

        English
        ----
        Compile one rule into the right bucket.

        The rule must have ``.selector`` (``ResourceSelector``) and
        ``.priority`` (``int``) attributes; otherwise ``ValueError``.
        """
        try:
            selector = rule.selector
            priority = rule.priority
        except AttributeError as e:
            raise ValueError(
                f"Rule {rule_id!r} missing required attribute: {e}"
            ) from e
        if not isinstance(selector, ResourceSelector):
            raise ValueError(
                f"Rule {rule_id!r}.selector must be ResourceSelector "
                f"(got {type(selector).__name__})"
            )
        if not isinstance(priority, int):
            raise ValueError(
                f"Rule {rule_id!r}.priority must be int (got {type(priority).__name__})"
            )
        item = IndexedRule(
            rule_id=rule_id, priority=priority, selector=selector, rule=rule
        )
        if selector.kind is SelectorKind.EXACT:
            bucket = self._exact.setdefault(selector.pattern, [])
        elif selector.kind is SelectorKind.PREFIX:
            bucket = self._prefix.setdefault(selector.pattern, [])
        elif selector.kind is SelectorKind.GLOB:
            bucket = self._glob.setdefault(selector.pattern, [])
        else:
            raise ValueError(f"unknown selector kind: {selector.kind!r}")
        bucket.append(item)
        # Keep bucket sorted by (priority desc, rule_id asc)
        bucket.sort(key=lambda x: (-x.priority, x.rule_id))

    def find(self, resource_name: str) -> list[IndexedRule]:
        """中文
        ----
        查找命中 ``resource_name`` 的所有 rule,按优先级排序。

        排序: EXACT > PREFIX > GLOB;同 kind 内按 priority desc + rule_id asc。

        English
        --------
        Find all rules matching ``resource_name``, sorted by priority.

        Sort: EXACT > PREFIX > GLOB; within kind, by priority desc +
        rule_id asc.
        """
        results: list[IndexedRule] = []

        # 1. EXACT
        for item in self._exact.get(resource_name, ()):
            results.append(item)

        # 2. PREFIX (most specific first: longest prefix wins)
        # PREFIX bucket key = pattern (e.g., "orders/..."), we strip "..."
        prefix_matches: list[IndexedRule] = []
        for pattern, items in self._prefix.items():
            prefix = pattern[:-3]  # strip "..."
            if resource_name.startswith(prefix):
                prefix_matches.extend(items)
        # Sort by prefix length desc (more specific first), then priority
        # desc, then rule_id asc
        prefix_matches.sort(
            key=lambda x: (-len(x.selector.pattern[:-3]), -x.priority, x.rule_id)
        )
        results.extend(prefix_matches)

        # 3. GLOB (loosest; sort by priority desc, rule_id asc)
        glob_matches: list[IndexedRule] = []
        for pattern, items in self._glob.items():
            if items and items[0].selector.matches(resource_name):
                glob_matches.extend(items)
        glob_matches.sort(key=lambda x: (-x.priority, x.rule_id))
        results.extend(glob_matches)

        return results

    def __len__(self) -> int:
        return sum(len(b) for b in self._exact.values()) + sum(
            len(b) for b in self._prefix.values()
        ) + sum(len(b) for b in self._glob.values())

    def snapshot_rules(self) -> Mapping[str, Any]:
        """中文
        ----
        返回索引内的 rule dict(只读视图,key = rule_id)。

        English
        --------
        Return rule dict in the index (read-only view, key = rule_id).
        """
        out: dict[str, Any] = {}
        for items in self._exact.values():
            for item in items:
                out[item.rule_id] = item.rule
        for items in self._prefix.values():
            for item in items:
                out[item.rule_id] = item.rule
        for items in self._glob.values():
            for item in items:
                out[item.rule_id] = item.rule
        return MappingProxyType(out)


__all__ = ["IndexedRule", "RuleIndex"]
