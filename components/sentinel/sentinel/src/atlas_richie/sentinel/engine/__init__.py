"""Sentinel Engine 子包(M1.2)。

中文
----
集中 re-export Engine / Slot / SlotChain / Entry 相关公共类型。

English
--------
Engine sub-package (M1.2). Centralised re-export of Engine / Slot /
SlotChain / Entry public types."""

from __future__ import annotations

from .entry import EntryLease, EntryRequest
from .sentinel_engine import FailSafe, OutcomeObserver, SentinelEngine
from .slot import (
    ORDER_AUTHORITY,
    ORDER_DEGRADE,
    ORDER_FLOW,
    ORDER_NODE_SELECTOR,
    ORDER_PARAM_FLOW,
    ORDER_STATISTIC,
    ORDER_SYSTEM,
    ORDER_USER_MAX,
    ORDER_USER_MIN,
    Slot,
)
from .slot_chain import SlotChain

__all__ = [
    # engine
    "SentinelEngine",
    "FailSafe",
    "OutcomeObserver",
    # entry
    "EntryRequest",
    "EntryLease",
    # slot
    "Slot",
    "SlotChain",
    "ORDER_NODE_SELECTOR",
    "ORDER_STATISTIC",
    "ORDER_AUTHORITY",
    "ORDER_SYSTEM",
    "ORDER_FLOW",
    "ORDER_PARAM_FLOW",
    "ORDER_DEGRADE",
    "ORDER_USER_MIN",
    "ORDER_USER_MAX",
]
