"""Spring AI metadata filter DSL 编译器。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    SpringAiVectorFilterCompiler,
    VectorFilter,
    VectorFilterCompiler,
    and_,
    contains_any,
    eq,
    exists,
    in_,
    not_,
    or_,
    range_,
)


@pytest.fixture
def compiler() -> SpringAiVectorFilterCompiler:
    return SpringAiVectorFilterCompiler()


class TestOutput:
    def test_eq_string_is_quoted(self, compiler) -> None:
        assert compiler.compile(eq("country", "CN")) == "country == 'CN'"

    def test_eq_number_is_bare(self, compiler) -> None:
        assert compiler.compile(eq("tenantId", 7)) == "tenantId == 7"
        assert compiler.compile(eq("score", 0.25)) == "score == 0.25"

    def test_boolean_is_lowercase(self, compiler) -> None:
        """Java String.valueOf(boolean) 是小写；Python str(True) 不是。"""
        assert compiler.compile(eq("active", True)) == "active == true"
        assert compiler.compile(eq("active", False)) == "active == false"

    def test_in_list(self, compiler) -> None:
        assert compiler.compile(in_("tenantId", ["t1", "t2"])) == "tenantId IN ['t1', 't2']"

    def test_contains_any_uses_in_dsl(self, compiler) -> None:
        assert (
            compiler.compile(contains_any("allowedDepartmentIds", ["d1"]))
            == "allowedDepartmentIds IN ['d1']"
        )

    def test_exists(self, compiler) -> None:
        assert compiler.compile(exists("source")) == "source != null"

    def test_not_wraps_in_parens(self, compiler) -> None:
        assert compiler.compile(not_(eq("a", 1))) == "NOT (a == 1)"

    def test_and_or_join(self, compiler) -> None:
        tree = and_(eq("a", 1), or_(eq("b", 2), eq("c", 3)))
        assert compiler.compile(tree) == "(a == 1 AND (b == 2 OR c == 3))"

    def test_single_child_combinator(self, compiler) -> None:
        assert compiler.compile(and_(eq("a", 1))) == "(a == 1)"

    @pytest.mark.parametrize(
        ("node", "expected"),
        [
            (range_("s", 0.2, None), "s >= 0.2"),
            (range_("s", None, 0.9), "s <= 0.9"),
            (range_("s", 0.2, 0.9), "(s >= 0.2 AND s <= 0.9)"),
        ],
    )
    def test_range_bounds(self, compiler, node, expected) -> None:
        assert compiler.compile(node) == expected

    def test_single_quote_is_escaped(self, compiler) -> None:
        assert compiler.compile(eq("name", "O'Brien")) == "name == 'O\\'Brien'"


class TestSafety:
    @pytest.mark.parametrize(
        "field",
        ["a b", "a;b", "${jndi:x}", "a-b", "1abc", "a'b", "DROP TABLE x", "a.b"],
    )
    def test_illegal_field_rejected(self, compiler, field) -> None:
        with pytest.raises(ValueError, match="illegal filter field"):
            compiler.compile(eq(field, 1))

    def test_value_cannot_break_out_of_literal(self, compiler) -> None:
        compiled = compiler.compile(eq("name", "x' OR '1'='1"))
        assert compiled == "name == 'x\\' OR \\'1\\'=\\'1'"
        assert compiled.count("'") % 2 == 0

    def test_unknown_node_type_is_rejected(self, compiler) -> None:
        class Rogue(VectorFilter):
            pass

        with pytest.raises(TypeError, match="unsupported vector filter node"):
            compiler.compile(Rogue())

    def test_satisfies_compiler_protocol(self, compiler) -> None:
        assert isinstance(compiler, VectorFilterCompiler)