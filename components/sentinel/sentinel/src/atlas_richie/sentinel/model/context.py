"""Sentinel 调用上下文(不可变、context-isolated)。

中文
----
``SentinelContext`` 是 Engine 在 ``engine.entry(...)`` 期间传给 Slot / 规则
的只读视图。所有跨 Slot 传递的状态(规则匹配结果、Token 句柄、链路 trace id)
都通过它共享;Engine 自身在每个 entry 路径上写一次,Slot 读多次。

设计要点:

- **frozen + slots=True**:防止 Slot 误改,共享给所有 Slot 之前已被冻结
- **无 ``put`` / ``set``**:只能整体替换(``with`` 模式),避免出现"半新半旧"状态
- **contextvars 隔离**:`trace_id` 来自 `contextvars.ContextVar`,跨 await 自然传播

English
--------
Sentinel call context (immutable, context-isolated).

``SentinelContext`` is the read-only view passed by ``Engine.entry`` to
every Slot / rule on the entry path. All cross-Slot state (rule matches,
Token handles, trace id) flows through it; the Engine writes once per
entry and Slots only read.

Design points:

- **frozen + slots=True** — prevents accidental Slot mutation.
- **no put / set** — only whole-replace via ``with`` pattern, so
  callers never see a half-updated state.
- **contextvars isolation** — ``trace_id`` propagates naturally across
  awaits via ``contextvars.ContextVar``."""

from __future__ import annotations

import contextvars
import secrets
import time
import uuid
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping

TraceId = str
"""Trace / correlation id, generated as a UUID4 string by default."""


def _new_trace_id() -> TraceId:
    """Generate a fresh trace id (UUID4 hex)."""
    return uuid.uuid4().hex


def _new_entered_at_ns() -> int:
    """Wall-clock nanoseconds at context construction; informational only."""
    return time.time_ns()


@dataclass(frozen=True, slots=True)
class SentinelContext:
    """中文
    ----
    Engine entry 期间的不可变共享视图。

    - `trace_id` — UUID4 字符串,用于跨 Slot / 跨 entry 关联指标与事件
    - `entered_at_ns` — 上下文创建时刻(``time.time_ns()``,仅作信息记录)
    - `extra` — 任意额外只读属性;``__post_init__`` 包装为 ``MappingProxyType``
    - `_annotations` — 内部字段,Slot 临时记录(例如"我已尝试 X 规则")
      通过 ``with_annotation(key, value)`` 整体替换实现追加

    English
    --------
    Immutable shared view for the duration of an Engine entry.

    - ``trace_id`` — UUID4 string, correlates metrics / events across
      Slots and entries.
    - ``entered_at_ns`` — wall-clock nanoseconds at construction
      (informational only).
    - ``extra`` — arbitrary read-only extras; ``__post_init__`` wraps in
      ``MappingProxyType``.
    - ``_annotations`` — internal field for Slot-side bookkeeping (e.g.
      "I tried rule X"); updates go through ``with_annotation`` which
      returns a new context.
    """

    trace_id: TraceId = field(default_factory=_new_trace_id)
    entered_at_ns: int = field(default_factory=_new_entered_at_ns)
    extra: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    _annotations: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # Wrap mutable dicts / lists in read-only views
        if not isinstance(self.extra, MappingProxyType):
            object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))
        if not isinstance(self._annotations, MappingProxyType):
            object.__setattr__(
                self, "_annotations", MappingProxyType(dict(self._annotations))
            )

    def annotation(self, key: str, default: Any = None) -> Any:
        """中文
        ----
        读 annotation;未命中返回 ``default``。

        English
        --------
        Read an annotation; return ``default`` when missing.
        """
        return self._annotations.get(key, default)

    def with_annotation(self, key: str, value: Any) -> "SentinelContext":
        """中文
        ----
        返回**新** context,带新增/覆盖的 annotation。原 context 保持不变。

        English
        --------
        Return a **new** context with the annotation added or replaced.
        The original context is unchanged.
        """
        new_ann = dict(self._annotations)
        new_ann[key] = value
        return replace(self, _annotations=MappingProxyType(new_ann))

    def with_extra(self, key: str, value: Any) -> "SentinelContext":
        """中文
        ----
        返回新 context,extra 增加/覆盖一项。

        English
        --------
        Return a new context with one extra field added or replaced.
        """
        new_extra = dict(self.extra)
        new_extra[key] = value
        return replace(self, extra=MappingProxyType(new_extra))


# contextvar for downstream propagation (e.g. Adapter middleware)
_current_context: contextvars.ContextVar[SentinelContext | None] = contextvars.ContextVar(
    "atlas_richie_sentinel_current_context", default=None
)


def current_context() -> SentinelContext | None:
    """中文
    ----
    读取当前 entry 路径上的 ``SentinelContext``(若已通过
    ``bind_current_context`` 绑定);未绑定返回 ``None``。

    English
    --------
    Read the ``SentinelContext`` bound to the current entry path
    (via ``bind_current_context``); returns ``None`` when unbound.
    """
    return _current_context.get()


def bind_current_context(ctx: SentinelContext) -> contextvars.Token:
    """中文
    ----
    把 context 绑定到当前 ``contextvars`` 上下文,返回 token 用于
    ``reset_current_context``。**只**由 Engine 在进入 entry 时调用;
    Adapter / 业务代码**不要**直接调用。

    English
    --------
    Bind a context to the current ``contextvars`` context; returns a
    token for ``reset_current_context``. Called by the Engine at entry
    time; Adapter / user code must not call this directly.
    """
    return _current_context.set(ctx)


def reset_current_context(token: contextvars.Token) -> None:
    """中文
    ----
    还原 ``bind_current_context`` 绑定的 context。Engine 在 entry 退出
    时调用,保证不会污染其它 entry。

    English
    --------
    Restore the context bound by ``bind_current_context``. Called by
    the Engine at entry exit so other entries are not polluted.
    """
    _current_context.reset(token)


__all__ = [
    "SentinelContext",
    "TraceId",
    "current_context",
    "bind_current_context",
    "reset_current_context",
    # Keep secrets / uuid imports alive for diagnostics
    "secrets",
]
