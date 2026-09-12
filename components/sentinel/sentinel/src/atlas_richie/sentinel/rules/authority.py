"""Sentinel AuthorityRule(M2.5)。

中文
----
``AuthorityRule`` 实现黑白名单 + 可信 origin 强制。Order=300
(Slot 在 Authority 阶段,Flow 之前)。**默认禁用** 客户端自报身份 —
``OriginResolver`` 必须配置才能解出 origin(否则拒绝 + 审计)。

设计要点:

- 2 种 ``AuthorityStrategy``:
  - ``ALLOW_LIST`` — 只允许白名单里的 origin
  - ``DENY_LIST`` — 黑名单里的 origin 拒绝
- ``origins`` — list[str] / set[str];ALLOW_LIST 模式下空 = 全部允许
  (危险,但保留为合法配置)
- 校验:strategy 必填,origins list 可空

English
--------
Sentinel AuthorityRule (M2.5).

``AuthorityRule`` implements allow/deny list + trusted origin
enforcement. Order=300 (Slot in Authority phase, before Flow).
**Default disables** client self-reported identity — ``OriginResolver``
must be configured to extract origin (otherwise reject + audit).

Design points:

- 2 ``AuthorityStrategy``s:
  - ``ALLOW_LIST`` — only allow listed origins.
  - ``DENY_LIST`` — deny listed origins.
- ``origins`` — list[str] / set[str]; ALLOW_LIST with empty list =
  allow all (dangerous but valid config).
- Validation: strategy required; origins list may be empty."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from ..errors import SentinelConfigurationError
from .selector import ResourceSelector


class AuthorityStrategy(StrEnum):
    """中文
    ----
    黑白名单策略。

    English
    --------
    Allow / deny list strategy.
    """

    ALLOW_LIST = "allow_list"
    DENY_LIST = "deny_list"


@dataclass(frozen=True, slots=True)
class AuthorityRule:
    """中文
    ----
    不可变 AuthorityRule。

    字段:

    - ``rule_id``, ``selector``, ``priority`` — 共享
    - ``strategy`` — ALLOW_LIST / DENY_LIST
    - ``origins`` — origin 列表(具体字符串);ALLOW_LIST 空 = 全部
      允许(危险)
    - ``default_deny_unresolved`` — True 时若 ``OriginResolver``
      解不出 origin,直接拒绝;False 时跳过(只对已解析的 origin 生效)

    构造校验(违反抛 ``SentinelConfigurationError``):rule_id 非空。

    English
    --------
    Immutable AuthorityRule.

    Fields:

    - ``rule_id``, ``selector``, ``priority`` — shared.
    - ``strategy`` — ALLOW_LIST / DENY_LIST.
    - ``origins`` — origin list (strings); ALLOW_LIST empty = allow
      all (dangerous).
    - ``default_deny_unresolved`` — True: if ``OriginResolver`` returns
      ``None``, deny; False: skip (only resolved origins participate).

    Construction validation (violations raise
    ``SentinelConfigurationError``): rule_id non-empty.
    """

    rule_id: str
    selector: ResourceSelector
    priority: int
    strategy: AuthorityStrategy
    origins: tuple[str, ...] = ()
    default_deny_unresolved: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise SentinelConfigurationError(
                "AuthorityRule rule_id must be non-empty",
                field="authority.rule_id",
                reason="validation_failed",
            )

    def is_allowed(self, origin: str) -> bool:
        """中文
        ----
        判定 origin 是否通过(根据 strategy + origins)。

        English
        --------
        Check whether origin passes (per strategy + origins).
        """
        if self.strategy is AuthorityStrategy.ALLOW_LIST:
            return origin in self.origins
        if self.strategy is AuthorityStrategy.DENY_LIST:
            return origin not in self.origins
        raise ValueError(f"unknown strategy: {self.strategy!r}")


__all__ = ["AuthorityStrategy", "AuthorityRule"]
