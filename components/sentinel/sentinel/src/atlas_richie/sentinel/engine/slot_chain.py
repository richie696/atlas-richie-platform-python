"""Sentinel SlotChain(M1.2)。

中文
----
``SlotChain`` 是 ``SentinelEngine`` 持有的有序 Slot 集合;每次 entry
时按 Order 升序遍历 ``enter``;任一 Slot 抛 ``SentinelBlockedError`` 即
短路。

设计要点:

- **稳定排序**:重复 ``add_slot`` / ``remove_slot`` 不会打乱原有顺序
  (按 ``(order, slot_id)`` 稳定排序;Order 相同时按插入顺序)
- **不可变快照** (``frozen_slots``):Engine 在 READY 状态时调用
  ``frozen_slots()`` 拿一份 tuple 用于本次 entry 期间的并发执行;
  后续 ``add_slot`` 不会影响在飞 entry
- **同名 Slot**:支持同一 Order 多个 Slot(测试用 stub / 影子);
  重复添加相同 ``id`` 的 Slot 会抛 ``SentinelConfigurationError``

English
--------
Sentinel SlotChain (M1.2).

``SlotChain`` is the Engine's ordered set of Slots; on every entry it
walks ``enter`` in Order ascending; any Slot raising
``SentinelBlockedError`` short-circuits.

Design points:

- **Stable sort** — repeated ``add_slot`` / ``remove_slot`` preserves
  insertion order for same-Order Slots (sorted by ``(order, slot_id)``).
- **Immutable snapshot** (``frozen_slots``) — the Engine takes a tuple
  in READY state for a given entry so concurrent in-flight entries
  are not affected by subsequent ``add_slot``.
- **Same-name Slot** — multiple Slots at the same Order (test stubs /
  shadows) are supported; re-adding the same ``id`` raises
  ``SentinelConfigurationError``."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import TYPE_CHECKING

from ..errors import SentinelConfigurationError
from .slot import Slot

if TYPE_CHECKING:
    pass


class SlotChain:
    """中文
    ----
    Engine 持有的有序 Slot 集合。

    - ``add_slot(slot)`` — 添加;Order 必须 > 0;重复 id 抛
      ``SentinelConfigurationError``
    - ``remove_slot(slot_id)`` — 按 id 移除;不存在返回 ``False``
    - ``frozen_slots()`` — 返回按 Order 升序的 tuple 快照,供本次
      entry 期间稳定使用

    English
    --------
    Engine-owned ordered set of Slots.

    - ``add_slot(slot)`` — add; Order must be > 0; duplicate id raises
      ``SentinelConfigurationError``.
    - ``remove_slot(slot_id)`` — remove by id; returns ``False`` when
      missing.
    - ``frozen_slots()`` — return a tuple snapshot sorted by Order
      ascending, stable for the duration of one entry.
    """

    _COUNTER = itertools.count()
    """中文
    ----
    模块级单调计数器,用于稳定排序同 Order Slot 的插入次序。

    English
    --------
    Module-level monotonic counter for stable insertion order of
    same-Order Slots.
    """

    def __init__(self) -> None:
        # list of (insertion_seq, slot) — insertion_seq provides a
        # total order for stable sorting when order values tie.
        self._slots: list[tuple[int, Slot]] = []
        self._by_id: dict[str, Slot] = {}

    def add_slot(self, slot: Slot) -> None:
        """中文
        ----
        添加一个 Slot。重复 id 抛 ``SentinelConfigurationError``。

        English
        --------
        Add a Slot. Duplicate id raises ``SentinelConfigurationError``.
        """
        slot_id = id(slot)
        if slot_id in self._by_id:
            raise SentinelConfigurationError(
                f"SlotChain: slot id {slot_id} already added",
                field="slot_chain",
                reason="duplicate_slot_id",
                value=slot_id,
            )
        order = slot.order
        if order <= 0:
            raise SentinelConfigurationError(
                f"SlotChain: slot order must be > 0 (got {order})",
                field="slot.order",
                reason="non_positive_order",
                value=order,
            )
        seq = next(self._COUNTER)
        self._by_id[slot_id] = slot
        self._slots.append((seq, slot))

    def remove_slot(self, slot: Slot) -> bool:
        """中文
        ----
        按 id 移除 Slot;不存在返回 ``False``。

        English
        --------
        Remove a Slot by id; returns ``False`` when missing.
        """
        slot_id = id(slot)
        slot_obj = self._by_id.pop(slot_id, None)
        if slot_obj is None:
            return False
        # Remove from insertion list (linear scan, expected chain is small)
        self._slots = [(s, x) for s, x in self._slots if x is not slot_obj]
        return True

    def frozen_slots(self) -> tuple[Slot, ...]:
        """中文
        ----
        返回按 ``(order, insertion_seq)`` 升序的 Slot tuple 快照。

        English
        --------
        Return a tuple snapshot sorted by ``(order, insertion_seq)``
        ascending.
        """
        return tuple(
            slot for _, slot in sorted(
                self._slots,
                key=lambda pair: (pair[1].order, pair[0]),
            )
        )

    def __len__(self) -> int:
        return len(self._slots)

    def __iter__(self) -> Iterator[Slot]:
        return iter(self.frozen_slots())

    def __contains__(self, slot: object) -> bool:
        return isinstance(slot, Slot) and id(slot) in self._by_id


__all__ = ["SlotChain"]
