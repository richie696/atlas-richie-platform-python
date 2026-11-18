"""过滤树 → provider 服务端过滤语法的编译器。

对应 Java `cn.richie696.component.vector.filter`。核心层只内置 Spring AI
metadata filter DSL 一种（Redis / pgvector / Weaviate 等 Spring AI provider
共用）；其它 DSL（Milvus 表达式、Qdrant JSON、参数化 SQL）由适配器自带编译器
实现同一个 `VectorFilterCompiler` 协议。

安全约束与 Java 一致：字段名必须匹配合法标识符，字面量做单引号转义，
调用方无法借业务过滤把任意表达式注入 provider。
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from .filters import (
    And,
    ContainsAny,
    Eq,
    Exists,
    In,
    Not,
    Or,
    Range,
    VectorFilter,
)

_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@runtime_checkable
class VectorFilterCompiler(Protocol):
    def compile(self, filter: VectorFilter) -> str: ...


class SpringAiVectorFilterCompiler:
    """编译为 Spring AI metadata filter DSL 字符串。"""

    def compile(self, filter: VectorFilter) -> str:
        match filter:
            case Eq(field=field, value=value):
                return f"{_field(field)} == {_literal(value)}"
            case In(field=field, values=values):
                return f"{_field(field)} IN {_list(values)}"
            case ContainsAny(field=field, values=values):
                return f"{_field(field)} IN {_list(values)}"
            case Range() as node:
                return _range(node)
            case Exists(field=field):
                return f"{_field(field)} != null"
            case Not(filter=inner):
                return f"NOT ({self.compile(inner)})"
            case And(filters=children):
                return "(" + " AND ".join(self.compile(c) for c in children) + ")"
            case Or(filters=children):
                return "(" + " OR ".join(self.compile(c) for c in children) + ")"
            case _:
                raise TypeError(
                    f"unsupported vector filter node: {type(filter).__name__}"
                )


def _field(field: str) -> str:
    if not isinstance(field, str) or not _FIELD.fullmatch(field):
        raise ValueError(f"illegal filter field: {field!r}")
    return field


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "\\'") + "'"


def _list(values: tuple[Any, ...]) -> str:
    return "[" + ", ".join(_literal(v) for v in values) + "]"


def _range(node: Range) -> str:
    field = _field(node.field)
    lower, upper = node.greater_than_or_equal, node.less_than_or_equal
    if lower is None:
        return f"{field} <= {_literal(upper)}"
    if upper is None:
        return f"{field} >= {_literal(lower)}"
    return f"({field} >= {_literal(lower)} AND {field} <= {_literal(upper)})"


__all__ = ["VectorFilterCompiler", "SpringAiVectorFilterCompiler"]