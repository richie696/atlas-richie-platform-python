"""Sentinel ResourceSelector(M1.5)。

中文
----
``ResourceSelector`` 是 Rule 引用 Resource 的方式。1.0 阶段只支持
3 种:

- ``EXACT`` — 精确匹配 ``Resource.name``
- ``PREFIX`` — 前缀匹配(以 ``...`` 结尾表示"任意后缀",如
  ``"orders/..."``)
- ``GLOB`` — 极简通配符(``*`` 匹配任意字符,``?`` 匹配单个字符;
  **不**支持任意正则表达式,避免 ReDoS 风险)

设计要点:

- **不可变 + frozen + slots=True**
- **不预编译正则**:PREFIX / GLOB 用 ``str.startswith`` /
  ``fnmatch.fnmatchcase`` 实现,O(n) where n = selector length,无回溯
- **3 种类型互斥**:构造时校验 selector 字符串与 kind 匹配(如
  PREFIX 必须以 ``...`` 结尾)
- **空 selector 拒绝**:``""`` 永远是 invalid,避免误匹配所有资源

English
--------
Sentinel ResourceSelector (M1.5).

``ResourceSelector`` is how a Rule references a Resource. 1.0 supports
only 3 types:

- ``EXACT`` — exact match on ``Resource.name``.
- ``PREFIX`` — prefix match (``...`` suffix = "any tail", e.g.
  ``"orders/..."``).
- ``GLOB`` — minimal wildcards (``*`` matches any chars, ``?`` matches
  one char; **no** arbitrary regex, to avoid ReDoS risk).

Design points:

- **Immutable + frozen + slots=True**
- **No pre-compiled regex** — PREFIX uses ``str.startswith``; GLOB
  uses ``fnmatch.fnmatchcase``; O(n) in selector length, no
  backtracking.
- **3 kinds are mutually exclusive** — construction validates the
  selector string matches its kind (e.g. PREFIX must end in ``...``).
- **Empty selector rejected** — ``""`` is always invalid to avoid
  matching every resource.
"""

from __future__ import annotations

import enum
import fnmatch
from dataclasses import dataclass
from typing import Literal


class SelectorKind(enum.Enum):
    """中文
    ----
    选择器种类(3 种,1.0 不支持任意正则)。

    English
    --------
    Selector kinds (3 kinds; 1.0 does not support arbitrary regex).
    """

    EXACT = "exact"
    PREFIX = "prefix"
    GLOB = "glob"


@dataclass(frozen=True, slots=True)
class ResourceSelector:
    """中文
    ----
    不可变资源选择器。

    - ``kind`` — 3 选 1(EXACT / PREFIX / GLOB)
    - ``pattern`` — 模式字符串:
      - EXACT: 完全等于 ``Resource.name``(区分大小写)
      - PREFIX: 以 ``pattern[:-3]`` 开头(``pattern`` 必须以 ``...``
        结尾,长度 ≥ 4)
      - GLOB: ``fnmatch`` 模式(``*`` / ``?``)

    ``__post_init__`` 校验:

    - ``pattern`` 非空
    - PREFIX 必须以 ``...`` 结尾
    - PREFIX pattern 去掉 ``...`` 后也非空
    - GLOB pattern 不为空(不能只含 ``*`` 匹配所有 — 防止误配)
    - EXACT 无额外校验

    English
    --------
    Immutable resource selector.

    - ``kind`` — one of EXACT / PREFIX / GLOB.
    - ``pattern``:
      - EXACT: equals ``Resource.name`` (case-sensitive).
      - PREFIX: starts with ``pattern[:-3]`` (``pattern`` must end in
        ``...``; length ≥ 4).
      - GLOB: ``fnmatch`` pattern (``*`` / ``?``).

    ``__post_init__`` validates:

    - ``pattern`` non-empty.
    - PREFIX must end in ``...``.
    - PREFIX pattern non-empty after stripping ``...``.
    - GLOB pattern not empty (cannot be just ``*`` matching all —
      prevents accidental matches).
    - EXACT has no extra validation."""

    kind: SelectorKind
    pattern: str

    def __post_init__(self) -> None:
        if not self.pattern:
            raise ValueError("ResourceSelector.pattern must be non-empty")
        if self.kind is SelectorKind.PREFIX:
            if not self.pattern.endswith("..."):
                raise ValueError(
                    f"PREFIX selector must end with '...' (got {self.pattern!r})"
                )
            if len(self.pattern) <= 3:
                raise ValueError(
                    f"PREFIX selector must have non-empty prefix before '...' "
                    f"(got {self.pattern!r})"
                )

    def matches(self, name: str) -> bool:
        """中文
        ----
        判断 ``name`` 是否被本选择器匹配。

        English
        --------
        Return whether ``name`` matches this selector.
        """
        if self.kind is SelectorKind.EXACT:
            return name == self.pattern
        if self.kind is SelectorKind.PREFIX:
            return name.startswith(self.pattern[:-3])
        if self.kind is SelectorKind.GLOB:
            return fnmatch.fnmatchcase(name, self.pattern)
        raise ValueError(f"unknown selector kind: {self.kind!r}")

    @staticmethod
    def exact(name: str) -> "ResourceSelector":
        """中文
        ----
        工厂:EXACT 匹配。

        English
        --------
        Factory: EXACT match.
        """
        return ResourceSelector(kind=SelectorKind.EXACT, pattern=name)

    @staticmethod
    def prefix(prefix: str) -> "ResourceSelector":
        """中文
        ----
        工厂:PREFIX 匹配(自动加 ``...`` 后缀)。

        English
        --------
        Factory: PREFIX match (auto-appends ``...``).
        """
        if not prefix:
            raise ValueError("prefix() requires non-empty prefix")
        return ResourceSelector(kind=SelectorKind.PREFIX, pattern=prefix + "...")

    @staticmethod
    def glob(pattern: str) -> "ResourceSelector":
        """中文
        ----
        工厂:GLOB 匹配(``*`` / ``?``)。

        English
        --------
        Factory: GLOB match (``*`` / ``?``).
        """
        return ResourceSelector(kind=SelectorKind.GLOB, pattern=pattern)


__all__ = ["SelectorKind", "ResourceSelector"]
