"""Sentinel entry outcome(单次 entry 的终态)。

中文
----
``OutcomeKind`` 是 5 选 1 的状态机终态,``Outcome`` 是不可变的 final
record。Engine 在 entry 退出时构造一个 ``Outcome`` 并交给 Adapter /
metrics / events。

5 种状态严格互斥:

- ADMITTED — 进入 SlotChain 之前的中间态(罕见,主要用于分阶段记录)
- SUCCEEDED — 业务正常返回
- FAILED — 业务异常返回(归入 ``error``)
- CANCELLED — 协程被取消(asyncio.CancelledError)
- BLOCKED — 任一 Slot 拒绝,SentinelBlockedError 子类记录在 ``error``

测试中必须能区分这 5 种,不能合并为 SUCCEEDED / 其它二值。

English
--------
Sentinel entry outcome — the terminal state of a single entry.

``OutcomeKind`` is a 5-way enum; ``Outcome`` is the immutable final
record. The Engine constructs an ``Outcome`` at entry exit and hands
it to the Adapter / metrics / events.

The 5 states are strictly mutually exclusive:

- ``ADMITTED`` — pre-SlotChain intermediate (rare; for staged recording).
- ``SUCCEEDED`` — business returned normally.
- ``FAILED`` — business raised (captured in ``error``).
- ``CANCELLED`` — coroutine was cancelled (``asyncio.CancelledError``).
- ``BLOCKED`` — a Slot rejected; ``SentinelBlockedError`` subclass in
  ``error``.

Tests must distinguish all 5; merging to a binary passed/failed is a
SEN-CORE-001 regression."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .resource import Resource


class OutcomeKind(StrEnum):
    """中文
    ----
    Entry 终态枚举(5 选 1,严格互斥)。

    English
    --------
    Entry terminal state (5-way, strictly mutually exclusive).
    """

    ADMITTED = "admitted"     # 进入 SlotChain 之前
    SUCCEEDED = "succeeded"   # 业务正常返回
    FAILED = "failed"         # 业务异常返回
    CANCELLED = "cancelled"   # 协程被取消
    BLOCKED = "blocked"       # Slot 拒绝


@dataclass(frozen=True, slots=True)
class Outcome:
    """中文
    ----
    不可变 entry 终态记录。

    - `resource` — 受保护资源
    - `kind` — 5 选 1
    - `error` — 异常实例(``FAILED`` 时业务异常,``BLOCKED`` 时
      SentinelBlockedError,``CANCELLED`` 时 ``asyncio.CancelledError``,
      ``SUCCEEDED`` / ``ADMITTED`` 时为 ``None``)
    - `result` — 业务返回值(``SUCCEEDED`` 时设置,其它场景为 ``None``)
    - `elapsed_ns` — entry 耗时(纳秒,``Engine.entry()`` 退出时记录)
    - `trace_id` — 与 ``SentinelContext.trace_id`` 一致,方便关联

    English
    --------
    Immutable entry terminal record.

    - ``resource`` — protected resource.
    - ``kind`` — 5-way enum.
    - ``error`` — exception (``FAILED`` = business exc, ``BLOCKED`` =
      ``SentinelBlockedError`` subclass, ``CANCELLED`` =
      ``asyncio.CancelledError``, ``SUCCEEDED`` / ``ADMITTED`` = ``None``).
    - ``result`` — business return value (``SUCCEEDED`` only).
    - ``elapsed_ns`` — entry wall time in nanoseconds.
    - ``trace_id`` — same as ``SentinelContext.trace_id`` for correlation.
    """

    resource: Resource
    kind: OutcomeKind
    error: BaseException | None = None
    result: Any = None
    elapsed_ns: int = 0
    trace_id: str = ""

    def is_blocked(self) -> bool:
        return self.kind is OutcomeKind.BLOCKED

    def is_succeeded(self) -> bool:
        return self.kind is OutcomeKind.SUCCEEDED

    def is_failed(self) -> bool:
        return self.kind is OutcomeKind.FAILED

    def is_cancelled(self) -> bool:
        return self.kind is OutcomeKind.CANCELLED


__all__ = ["Outcome", "OutcomeKind"]
