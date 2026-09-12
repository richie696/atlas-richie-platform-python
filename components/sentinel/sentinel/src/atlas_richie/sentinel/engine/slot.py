"""Sentinel Slot 协议与 Order 常量(M1.2)。

中文
----
``Slot`` 是 Sentinel Engine 的最小可扩展点,SlotChain 按 Order 从小到大
依次调用 ``enter``;任何 Slot 抛 ``SentinelBlockedError`` 即短路
(后续 Slot 不再 ``enter``,但已 ``enter`` 的 Slot 必须 ``release`` /
``exit`` 对称释放)。

设计要点:

- **Protocol 形态**:Slot 接口用 ``Protocol`` 表达,允许 dataclass / 任何
  duck-typed 类实现,无需继承抽象基类
- **enter / exit 对称**:每次 ``enter`` 返回 ``SlotLease`` 或抛
  ``SentinelBlockedError``;Engine 在 entry 退出时**逆序**调用每个
  ``lease.release()``,Lease 自身负责释放资源
- **Order 常量**:7 个内置 Slot 的 Order 集中定义,数值按执行顺序递增
  (小 → 先),所有第三方 Slot 选 Order 100 / 300 / 500 / 700 中间值

English
--------
Sentinel Slot protocol and Order constants (M1.2).

``Slot`` is the smallest Engine extension point. ``SlotChain`` invokes
``enter`` in Order; any Slot raising ``SentinelBlockedError`` short-
circuits (subsequent Slots do not ``enter``, but already-entered
Slots must have their ``release`` / ``exit`` symmetrically called).

Design points:

- **Protocol form** — Slot interface uses ``Protocol`` so dataclasses
  or any duck-typed class can implement it without inheriting an
  abstract base.
- **enter / exit symmetry** — each ``enter`` returns ``SlotLease`` or
  raises ``SentinelBlockedError``; the Engine calls each lease's
  ``release()`` in **reverse** order at entry exit.
- **Order constants** — fixed values for the 7 built-in Slots;
  third-party Slots pick in-between values."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.outcome import Outcome
from ..model.resource import Resource


# ---------------------------------------------------------------------------
# Order 常量(7 个内置 Slot)
# ---------------------------------------------------------------------------

ORDER_NODE_SELECTOR = 100
"""中文
----
NodeSelectorSlot — 选择/验证 Resource(最低 Order,最先生效)。

English
--------
NodeSelectorSlot — picks / validates the Resource (lowest Order, fires
first)."""

ORDER_STATISTIC = 200
"""中文
----
StatisticSlot — 指标采样(在 NodeSelector 之后,Authority / System 之前;
这样被 Resource 校验拒绝的请求不计入指标)。

English
--------
StatisticSlot — metric sampling (after NodeSelector, before Authority /
System so Resource-rejected requests don't pollute metrics)."""

ORDER_AUTHORITY = 300
"""中文
----
AuthoritySlot — origin 黑/白名单(必须在 Flow 之前,让无权限请求
快速失败)。

English
--------
AuthoritySlot — origin allow/deny list (must be before Flow so
unauthorized requests fail fast)."""

ORDER_SYSTEM = 400
"""中文
----
SystemSlot — 进程级保护(CPU/load/QPS/in-flight;只对 INBOUND 资源)。

English
--------
SystemSlot — process-level protection (CPU/load/QPS/in-flight; only
fires on INBOUND resources)."""

ORDER_FLOW = 500
"""中文
----
FlowSlot — QPS / 并发限流(在所有"选择/校验"类 Slot 之后)。

English
--------
FlowSlot — QPS / concurrency limiting (after all "selection /
validation" Slots)."""

ORDER_PARAM_FLOW = 600
"""中文
----
ParamFlowSlot — 热点参数限流(在 Flow 之后,按参数 hash)。

English
--------
ParamFlowSlot — hot-spot parameter limiting (after Flow, by
parameter hash)."""

ORDER_DEGRADE = 700
"""中文
----
DegradeSlot — 降级/熔断(最高 Order,最后判定)。

English
--------
DegradeSlot — degrade / circuit breaking (highest Order, last word)."""

ORDER_USER_MIN = 150
"""中文
----
用户自定义 Slot 可选的最小 Order(在 NodeSelector 之后、Statistic 之前)。

English
--------
Minimum Order for user-defined Slots (after NodeSelector, before
Statistic)."""

ORDER_USER_MAX = 690
"""中文
----
用户自定义 Slot 可选的最大 Order(在 ParamFlow 之前、Degrade 之后)。

English
--------
Maximum Order for user-defined Slots (after ParamFlow, before
Degrade)."""


# ---------------------------------------------------------------------------
# Slot Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Slot(Protocol):
    """中文
    ----
    Sentinel Slot 协议。Engine 在每次 entry 时按 ``order`` 升序调用 ``enter``;

    - ``enter`` 同步实现(**非** coroutine),以便 Engine 能在同步阶段做
      Resource 校验等快速失败;真正需要 IO 的 Slot 内部用 ``asyncio.run``
      或类似机制(绝大多数场景是同步的)
    - 放行时返回 ``SlotLease``;拒绝时抛 ``SentinelBlockedError``
    - Engine 退出时**逆序**调用 ``lease.release()``;Lease 内部负责
      释放(令牌归还、permit 归还等)

    子接口:

    - ``on_entry_complete(outcome)`` — Engine 在 entry 完成时通知 Slot;
      DegradeSlot 用它来统计 success / failure 计数,ParamFlowSlot 用
      它来更新热点参数统计;**不抛**异常(失败要 swallow 到 metrics)

    English
    --------
    Sentinel Slot protocol. The Engine calls ``enter`` in ``order``
    ascending on every entry.

    - ``enter`` is synchronous (not a coroutine) so the Engine can do
      fast Resource validation in the synchronous phase; Slots that
      need IO use ``asyncio.run`` or similar.
    - On admit, returns ``SlotLease``; on reject, raises
      ``SentinelBlockedError``.
    - At entry exit, the Engine calls each ``lease.release()`` in
      **reverse** order; the Lease is responsible for resource release.

    Sub-interface:

    - ``on_entry_complete(outcome)`` — Engine notifies the Slot when
      entry completes; DegradeSlot uses it for success/failure counts,
      ParamFlowSlot for hot-spot parameter statistics; **must not**
      raise (failures are swallowed to metrics).
    """

    @property
    def order(self) -> int:
        """中文
        ----
        Slot 在 SlotChain 中的执行顺序。数值小 → 先执行。

        English
        --------
        Slot execution order in the chain. Smaller → earlier.
        """
        ...

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> "SlotLease":
        """中文
        ----
        Slot 入口判定。放行返回 ``SlotLease``;拒绝抛 ``SentinelBlockedError``。

        参数全部 keyword-only,避免 Engine 误传顺序错位。

        English
        --------
        Slot admission. Returns ``SlotLease`` on admit; raises
        ``SentinelBlockedError`` on reject.

        All parameters are keyword-only to prevent argument-order bugs
        at Engine call sites.
        """
        ...

    def on_entry_complete(self, outcome: Outcome) -> None:
        """中文
        ----
        entry 完成时通知 Slot(成功 / 失败 / 取消 / 拒绝都触发)。

        必须**不**抛异常 — 任何错误吞到 Slot 自己的 metrics,避免污染
        业务主流程。

        English
        --------
        Notify Slot on entry completion (fires for all 4 Outcome kinds).

        Must **not** raise — any error is swallowed to the Slot's own
        metrics so the business call site is not polluted.
        """
        ...


__all__ = [
    "ORDER_NODE_SELECTOR",
    "ORDER_STATISTIC",
    "ORDER_AUTHORITY",
    "ORDER_SYSTEM",
    "ORDER_FLOW",
    "ORDER_PARAM_FLOW",
    "ORDER_DEGRADE",
    "ORDER_USER_MIN",
    "ORDER_USER_MAX",
    "Slot",
]
