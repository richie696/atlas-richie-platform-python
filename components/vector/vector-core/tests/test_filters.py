"""过滤树工厂与结构约束。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    And,
    ContainsAny,
    Eq,
    Exists,
    In,
    Not,
    Or,
    Range,
    VectorFilter,
    and_,
    contains_any,
    eq,
    exists,
    in_,
    not_,
    or_,
    range_,
)


class TestFactories:
    def test_eq_keeps_value_type(self) -> None:
        assert eq("tenantId", 7) == Eq("tenantId", 7)
        assert eq("ok", True) == Eq("ok", True)

    def test_in_snapshots_values(self) -> None:
        values = ["a", "b"]
        node = in_("tag", values)
        values.append("c")
        assert node.values == ("a", "b"), "工厂必须快照，调用方后续修改不得影响过滤树"

    def test_contains_any_is_distinct_from_in(self) -> None:
        assert contains_any("d", ["x"]) == ContainsAny("d", ("x",))
        assert in_("d", ["x"]) == In("d", ("x",))
        assert contains_any("d", ["x"]) != in_("d", ["x"])

    def test_range_single_bound(self) -> None:
        assert range_("score", 0.2, None) == Range("score", 0.2, None)
        assert range_("score", None, 0.9) == Range("score", None, 0.9)

    def test_combinators(self) -> None:
        leaf = eq("a", 1)
        assert and_(leaf, leaf) == And((leaf, leaf))
        assert or_(leaf) == Or((leaf,))
        assert not_(leaf) == Not(leaf)
        assert exists("a") == Exists("a")

    def test_nodes_are_filter_subtypes(self) -> None:
        for node in (eq("a", 1), in_("a", [1]), exists("a"), not_(eq("a", 1))):
            assert isinstance(node, VectorFilter)

    def test_trees_are_hashable_and_comparable(self) -> None:
        left = and_(eq("a", 1), or_(eq("b", 2), exists("c")))
        right = and_(eq("a", 1), or_(eq("b", 2), exists("c")))
        assert left == right
        assert len({left, right}) == 1


class TestValidation:
    @pytest.mark.parametrize("field", ["", "   ", None, 7])
    def test_blank_field_rejected(self, field) -> None:
        with pytest.raises(ValueError):
            eq(field, 1)

    def test_eq_none_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            eq("a", None)

    @pytest.mark.parametrize("factory", [in_, contains_any])
    def test_empty_values_rejected(self, factory) -> None:
        with pytest.raises(ValueError):
            factory("a", [])

    def test_both_range_bounds_none_rejected(self) -> None:
        with pytest.raises(ValueError):
            range_("a", None, None)

    def test_empty_combinator_rejected(self) -> None:
        with pytest.raises(ValueError):
            and_()
        with pytest.raises(ValueError):
            or_()

    def test_not_none_rejected(self) -> None:
        with pytest.raises(ValueError):
            not_(None)

    def test_non_filter_child_rejected(self) -> None:
        with pytest.raises(TypeError):
            and_(eq("a", 1), "b == 2")