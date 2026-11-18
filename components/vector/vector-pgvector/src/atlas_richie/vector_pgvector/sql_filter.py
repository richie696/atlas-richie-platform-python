"""过滤树 → 参数化 JSONB 谓词。

与核心的 `SpringAiVectorFilterCompiler` 并列的另一种 `VectorFilterCompiler`
实现：不产出 DSL 字符串，而是产出 `(SQL 片段, 绑定参数)`。

**字段名也是绑定参数**（`metadata -> %s`），不做任何字符串拼接，因此即使
字段名来自不可信输入也无法注入 SQL。字面量以 `::jsonb` 绑定，保留原始类型
（数字按数字比较，不会被强转成字符串）。

`ContainsAny` 用 jsonb 的 `?|` 运算符：它判断"给定字符串集合中是否有任一
元素出现在 JSON 数组里"，正是 ACL 部门/主体交集语义。该运算符只接受字符串，
非字符串值会被拒绝而不是静默 str() 化。
"""

from __future__ import annotations

import json
import re
from typing import Any

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
    VectorQueryErrorCode,
    VectorQueryValidationException,
)

_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _field(field: str) -> str:
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise ValueError(f"illegal filter field: {field!r}")
    return field


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class SqlFilterCompiler:
    """编译为可直接拼进 WHERE 的参数化片段。"""

    def compile(self, filter: VectorFilter) -> tuple[str, list[Any]]:
        match filter:
            case Eq(field=field, value=value):
                return "metadata -> %s = %s::jsonb", [_field(field), _jsonb(value)]
            case In(field=field, values=values):
                return (
                    "metadata -> %s = ANY(%s::jsonb[])",
                    [_field(field), [_jsonb(v) for v in values]],
                )
            case ContainsAny(field=field, values=values):
                if any(not isinstance(v, str) for v in values):
                    raise VectorQueryValidationException(
                        VectorQueryErrorCode.UNSUPPORTED_OPTION,
                        "jsonb ?| only supports string set members",
                    )
                return "metadata -> %s ?| %s::text[]", [_field(field), list(values)]
            case Range() as node:
                return self._range(node)
            case Exists(field=field):
                return "metadata ? %s", [_field(field)]
            case Not(filter=inner):
                sql, params = self.compile(inner)
                return f"NOT ({sql})", params
            case And(filters=children):
                return self._join(children, " AND ")
            case Or(filters=children):
                return self._join(children, " OR ")
            case _:
                raise TypeError(
                    f"unsupported vector filter node: {type(filter).__name__}"
                )

    def _range(self, node: Range) -> tuple[str, list[Any]]:
        field = _field(node.field)
        lower, upper = node.greater_than_or_equal, node.less_than_or_equal
        if lower is None:
            return "metadata -> %s <= %s::jsonb", [field, _jsonb(upper)]
        if upper is None:
            return "metadata -> %s >= %s::jsonb", [field, _jsonb(lower)]
        return (
            "(metadata -> %s >= %s::jsonb AND metadata -> %s <= %s::jsonb)",
            [field, _jsonb(lower), field, _jsonb(upper)],
        )

    def _join(
        self, children: tuple[VectorFilter, ...], operator: str
    ) -> tuple[str, list[Any]]:
        parts: list[str] = []
        params: list[Any] = []
        for child in children:
            sql, child_params = self.compile(child)
            parts.append(sql)
            params.extend(child_params)
        return "(" + operator.join(parts) + ")", params


__all__ = ["SqlFilterCompiler"]