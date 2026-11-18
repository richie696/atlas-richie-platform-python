"""可下推到向量数据库的过滤表达式树。

对应 Java `cn.richie696.component.vector.model.VectorFilter`（sealed
interface + 8 个 record）。Python 没有 sealed，穷尽性由编译器的 `match`
兜底分支在运行时保证：新增节点若未被编译器处理会立刻抛 `TypeError`，
而不是静默漏掉一个 ACL 条件。

`In` 与 `ContainsAny` 的区别是 RAG ACL 的关键：前者是"标量字段 ∈ 集合"，
后者是"集合字段 ∩ 集合 ≠ ∅"（如用户所属部门 ∩ 记录的 allowedDepartmentIds）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


class VectorFilter:
    """表达式树基类。不直接实例化，用模块级工厂函数构造。"""

    __slots__ = ()


def _require_field(field: str) -> str:
    if not isinstance(field, str) or not field.strip():
        raise ValueError("field must not be blank")
    return field


def _require_values(values: Iterable[Any]) -> tuple[Any, ...]:
    snapshot = tuple(values) if values is not None else ()
    if not snapshot:
        raise ValueError("values must not be empty")
    return snapshot


def _require_children(filters: Sequence[VectorFilter]) -> tuple[VectorFilter, ...]:
    snapshot = tuple(filters) if filters is not None else ()
    if not snapshot:
        raise ValueError("filters must not be empty")
    for child in snapshot:
        if not isinstance(child, VectorFilter):
            raise TypeError(f"expected VectorFilter, got {type(child).__name__}")
    return snapshot


@dataclass(frozen=True, slots=True)
class Eq(VectorFilter):
    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class In(VectorFilter):
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ContainsAny(VectorFilter):
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class Range(VectorFilter):
    field: str
    greater_than_or_equal: Any = None
    less_than_or_equal: Any = None


@dataclass(frozen=True, slots=True)
class Exists(VectorFilter):
    field: str


@dataclass(frozen=True, slots=True)
class Not(VectorFilter):
    filter: VectorFilter


@dataclass(frozen=True, slots=True)
class And(VectorFilter):
    filters: tuple[VectorFilter, ...]


@dataclass(frozen=True, slots=True)
class Or(VectorFilter):
    filters: tuple[VectorFilter, ...]


def eq(field: str, value: Any) -> Eq:
    if value is None:
        raise ValueError("value must not be None")
    return Eq(_require_field(field), value)


def in_(field: str, values: Iterable[Any]) -> In:
    return In(_require_field(field), _require_values(values))


def contains_any(field: str, values: Iterable[Any]) -> ContainsAny:
    return ContainsAny(_require_field(field), _require_values(values))


def range_(
    field: str,
    greater_than_or_equal: Any = None,
    less_than_or_equal: Any = None,
) -> Range:
    if greater_than_or_equal is None and less_than_or_equal is None:
        raise ValueError("range bounds must not both be None")
    return Range(_require_field(field), greater_than_or_equal, less_than_or_equal)


def exists(field: str) -> Exists:
    return Exists(_require_field(field))


def not_(filter: VectorFilter) -> Not:
    if not isinstance(filter, VectorFilter):
        raise ValueError("filter must not be None")
    return Not(filter)


def and_(*filters: VectorFilter) -> And:
    return And(_require_children(filters))


def or_(*filters: VectorFilter) -> Or:
    return Or(_require_children(filters))


__all__ = [
    "VectorFilter",
    "Eq",
    "In",
    "ContainsAny",
    "Range",
    "Exists",
    "Not",
    "And",
    "Or",
    "eq",
    "in_",
    "contains_any",
    "range_",
    "exists",
    "not_",
    "and_",
    "or_",
]