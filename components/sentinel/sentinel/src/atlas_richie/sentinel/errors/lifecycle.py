"""Sentinel 生命周期异常(M1.1 引入)。

中文
----
两类:

- ``SentinelLifecycleError`` — Engine / RuleSource 状态机非法迁移
  (例如 SHUTDOWN → READY)
- ``RuleSnapshotError`` — 规则快照校验 / 解析失败,继承
  ``SentinelLifecycleError``

English
--------
Two lifecycle exception classes (M1.1):

- ``SentinelLifecycleError`` — illegal Engine / RuleSource state
  transitions (e.g. SHUTDOWN → READY).
- ``RuleSnapshotError`` — rule snapshot validation / parse failure;
  inherits ``SentinelLifecycleError``."""

from __future__ import annotations

from .base import SentinelError


class SentinelLifecycleError(SentinelError):
    """中文
    ----
    生命周期非法迁移。Engine 在状态机非法迁移时抛此异常(如重复进入
    ``async with`` / 在 SHUTDOWN 后再 ``entry()``)。

    - `from_state` — 迁移前状态(``EngineState`` 字符串)
    - `to_state` — 试图迁移到的状态
    - `component` — 哪个组件出错(``"engine"`` / ``"rule_source"`` / ...)

    English
    --------
    Illegal state transition. Raised by the Engine for invalid
    transitions (e.g. double ``async with`` entry, ``entry()`` after
    SHUTDOWN).

    - ``from_state`` — pre-transition state (string of ``EngineState``).
    - ``to_state`` — target state.
    - ``component`` — which component errored (``"engine"`` /
      ``"rule_source"`` / ...).
    """

    def __init__(
        self,
        message: str,
        *,
        from_state: str = "",
        to_state: str = "",
        component: str = "engine",
    ) -> None:
        super().__init__(message)
        self.from_state = from_state
        self.to_state = to_state
        self.component = component


class RuleSnapshotError(SentinelLifecycleError):
    """中文
    ----
    规则快照校验 / 解析失败。RuleSource 在加载 / 解析 / 校验规则
    快照时失败会抛此异常;Engine 不会应用该快照,继续保持旧规则运行
    (除非配置要求 fail-fast)。

    - `source_id` — RuleSource id
    - `version` — 快照版本(可空)
    - `reason` — 失败原因

    English
    --------
    Rule snapshot validation / parse failure. Raised when a RuleSource
    fails to load / parse / validate a snapshot. The Engine keeps the
    old rules in effect (unless configured to fail-fast).

    - ``source_id`` — RuleSource id.
    - ``version`` — snapshot version (may be empty).
    - ``reason`` — failure reason.
    """

    def __init__(
        self,
        message: str,
        *,
        source_id: str = "",
        version: str = "",
        reason: str = "",
    ) -> None:
        super().__init__(
            message,
            from_state="",
            to_state="",
            component="rule_source",
        )
        self.source_id = source_id
        self.version = version
        self.reason = reason


__all__ = ["SentinelLifecycleError", "RuleSnapshotError"]
