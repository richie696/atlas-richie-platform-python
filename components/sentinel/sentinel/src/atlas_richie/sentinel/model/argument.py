"""Sentinel 调用参数(用于 ParamFlowRule 热点参数限流)。

中文
----
``InvocationArguments`` 是 entry 的可选参数包,ParamFlowSlot 用它做
热点 key 提取。设计上保持**只读 + frozen**,以防 Slot 误改导致规则匹配
前后参数不一致。

English
--------
Sentinel invocation arguments (used by ParamFlowRule for hot-spot
parameter limiting).

``InvocationArguments`` is the optional argument bag passed at entry
time. ``ParamFlowSlot`` extracts hot-spot keys from it. The class is
frozen and read-only to prevent Slots from mutating arguments between
rule-match and rule-execute, which would produce inconsistent
observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

# Reasonable bound: prevents accidental DoS via huge kwargs
_MAX_ARG_KEYS = 64
_MAX_ARG_VALUE_LEN = 1024


@dataclass(frozen=True, slots=True)
class InvocationArguments:
    """中文
    ----
    Entry 期间传给 Slot 的只读参数包。

    - `positional` — 位置参数 tuple(Slot 不消费,只为完整性保留)
    - `keyword` — 关键字参数 ``Mapping[str, Any]``,ParamFlowSlot 提取热点 key
    - `hotspot_keys` — 显式指定的热点 key 列表;为空时 ParamFlowSlot
      默认取 ``keyword`` 的所有 key

    构造时校验 `keyword` 是 ``Mapping`` 实例(非任意 iterable),并
    限制 size / value 长度避免无界输入。

    English
    --------
    Read-only argument bag passed to Slots at entry time.

    - ``positional`` — positional args tuple (Slots do not consume; kept
      for completeness).
    - ``keyword`` — keyword args ``Mapping[str, Any]``; ParamFlowSlot
      extracts hot-spot keys.
    - ``hotspot_keys`` — explicit list of hot-spot keys; when empty,
      ParamFlowSlot falls back to all keys of ``keyword``.

    Construction enforces that ``keyword`` is a ``Mapping`` (not an
    arbitrary iterable) and caps size / value length to bound
    pathological inputs.
    """

    positional: tuple[Any, ...] = ()
    keyword: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    hotspot_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.positional, tuple):
            object.__setattr__(self, "positional", tuple(self.positional))
        if not isinstance(self.keyword, MappingProxyType):
            if not isinstance(self.keyword, Mapping):
                raise TypeError(
                    "InvocationArguments.keyword must be a Mapping "
                    "(use dict / MappingProxyType, not arbitrary iterable)"
                )
            if len(self.keyword) > _MAX_ARG_KEYS:
                raise ValueError(
                    f"InvocationArguments.keyword has {len(self.keyword)} keys "
                    f"(> {_MAX_ARG_KEYS}); refusing to construct"
                )
            bounded: dict[str, Any] = {}
            for k, v in self.keyword.items():
                if isinstance(v, (str, bytes)) and len(v) > _MAX_ARG_VALUE_LEN:
                    raise ValueError(
                        f"InvocationArguments.keyword[{k!r}] is {len(v)} bytes "
                        f"(> {_MAX_ARG_VALUE_LEN}); refusing to construct"
                    )
                bounded[str(k)] = v
            object.__setattr__(self, "keyword", MappingProxyType(bounded))
        if not isinstance(self.hotspot_keys, tuple):
            object.__setattr__(self, "hotspot_keys", tuple(self.hotspot_keys))

    def get(self, key: str, default: Any = None) -> Any:
        """中文
        ----
        按 key 取 keyword 参数;未命中返回 ``default``。

        English
        --------
        Look up a keyword arg by key; return ``default`` when missing.
        """
        return self.keyword.get(key, default)

    @property
    def is_empty(self) -> bool:
        """中文
        ----
        是否无任何参数(位置 + 关键字都为空)。

        English
        --------
        Whether no positional or keyword args are present.
        """
        return not self.positional and not self.keyword


__all__ = ["InvocationArguments", "_MAX_ARG_KEYS", "_MAX_ARG_VALUE_LEN"]
