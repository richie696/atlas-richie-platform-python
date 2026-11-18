"""参数化 JSONB 谓词编译（无需数据库）。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    VectorFilter,
    VectorQueryErrorCode,
    VectorQueryValidationException,
    and_,
    contains_any,
    eq,
    exists,
    in_,
    not_,
    or_,
    range_,
)
from atlas_richie.vector_pgvector import SqlFilterCompiler


@pytest.fixture
def compiler() -> SqlFilterCompiler:
    return SqlFilterCompiler()


class TestFragments:
    def test_eq_binds_field_and_value(self, compiler) -> None:
        sql, params = compiler.compile(eq("tenantId", 7))
        assert sql == "metadata -> %s = %s::jsonb"
        assert params == ["tenantId", "7"]

    def test_string_value_is_json_quoted(self, compiler) -> None:
        _, params = compiler.compile(eq("status", "ACTIVE"))
        assert params == ["status", '"ACTIVE"']

    def test_boolean_keeps_json_type(self, compiler) -> None:
        _, params = compiler.compile(eq("active", True))
        assert params == ["active", "true"]

    def test_in_uses_jsonb_array(self, compiler) -> None:
        sql, params = compiler.compile(in_("tag", ["a", "b"]))
        assert sql == "metadata -> %s = ANY(%s::jsonb[])"
        assert params == ["tag", ['"a"', '"b"']]

    def test_contains_any_uses_jsonb_existence_operator(self, compiler) -> None:
        sql, params = compiler.compile(contains_any("allowedDepartmentIds", ["d1", "d2"]))
        assert sql == "metadata -> %s ?| %s::text[]"
        assert params == ["allowedDepartmentIds", ["d1", "d2"]]

    def test_exists(self, compiler) -> None:
        assert compiler.compile(exists("source")) == ("metadata ? %s", ["source"])

    def test_not(self, compiler) -> None:
        sql, params = compiler.compile(not_(eq("a", 1)))
        assert sql == "NOT (metadata -> %s = %s::jsonb)"
        assert params == ["a", "1"]

    @pytest.mark.parametrize(
        ("node", "expected"),
        [
            (range_("s", 0.2, None), "metadata -> %s >= %s::jsonb"),
            (range_("s", None, 0.9), "metadata -> %s <= %s::jsonb"),
            (
                range_("s", 0.2, 0.9),
                "(metadata -> %s >= %s::jsonb AND metadata -> %s <= %s::jsonb)",
            ),
        ],
    )
    def test_range(self, compiler, node, expected) -> None:
        sql, params = compiler.compile(node)
        assert sql == expected
        assert params[0] == "s"

    def test_and_or_placeholders_and_params_stay_aligned(self, compiler) -> None:
        tree = and_(eq("tenantId", 7), or_(eq("status", "ACTIVE"), exists("source")))
        sql, params = compiler.compile(tree)
        assert sql.count("%s") == len(params), "占位符与参数个数必须一致"
        assert params == ["tenantId", "7", "status", '"ACTIVE"', "source"]
        assert sql == (
            "(metadata -> %s = %s::jsonb AND "
            "(metadata -> %s = %s::jsonb OR metadata ? %s))"
        )

    def test_nested_param_order_is_depth_first(self, compiler) -> None:
        tree = or_(
            and_(eq("a", 1), eq("b", 2)),
            and_(eq("c", 3), contains_any("d", ["x"])),
        )
        _, params = compiler.compile(tree)
        assert params == ["a", "1", "b", "2", "c", "3", "d", ["x"]]


class TestSafety:
    def test_value_never_reaches_sql_text(self, compiler) -> None:
        payload = "'; DROP TABLE vector_records; --"
        sql, params = compiler.compile(eq("name", payload))
        assert "DROP" not in sql
        assert payload in params[1]

    def test_field_name_is_bound_not_interpolated(self, compiler) -> None:
        sql, params = compiler.compile(eq("tenantId", 1))
        assert "tenantId" not in sql
        assert params[0] == "tenantId"

    @pytest.mark.parametrize("field", ["a b", "a;b", "a-b", "1abc", "a'b", ""])
    def test_illegal_field_rejected(self, compiler, field) -> None:
        with pytest.raises(ValueError):
            compiler.compile(eq(field, 1))

    def test_contains_any_rejects_non_string_members(self, compiler) -> None:
        with pytest.raises(VectorQueryValidationException) as info:
            compiler.compile(contains_any("allowedDepartmentIds", [1, 2]))
        assert info.value.code is VectorQueryErrorCode.UNSUPPORTED_OPTION

    def test_unknown_node_rejected(self, compiler) -> None:
        class Rogue(VectorFilter):
            pass

        with pytest.raises(TypeError):
            compiler.compile(Rogue())

    def test_unicode_value_is_not_escaped_to_ascii(self, compiler) -> None:
        _, params = compiler.compile(eq("name", "中文"))
        assert params == ["name", '"中文"']