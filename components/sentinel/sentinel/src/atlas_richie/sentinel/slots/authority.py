"""Sentinel AuthoritySlot + OriginResolver(M2.5)。

中文
----
``AuthoritySlot`` 在 Order=300 调用 ``OriginResolver.resolve(...)``
取 origin,再走黑白名单判定。

``OriginResolver`` Protocol 主包默认 ``DenyByDefaultOriginResolver``:
不识别任何 origin,所有解析结果都是 ``None``,强制 ``default_deny_unresolved=True``
时**全部拒绝**(安全默认)。M3.x Adapter 注入真实 resolver
(JWT / mTLS / 网关验签 / 内部服务账号)。

设计要点:

- **Order=300** 在 Statistic(200) 之后、System(400) 之前;让
  指标采样先走、无权限请求快速 fail-fast
- **default_deny_unresolved** True 时 resolver 返回 None → 直接抛
  ``AuthorityDenied``(不计入 metrics 命中,审计日志单独)
- **untrusted fallback** ``X-Origin`` header 走 ``UntrustedHeaderOriginResolver``;
  **不**默认启用,需要显式 ``engine.add_resolver(UntrustedHeaderOriginResolver(...))``
- **resolver 配置错误** → Slot 拒绝 + 审计(不静默通过)

English
--------
Sentinel AuthoritySlot + OriginResolver (M2.5).

``AuthoritySlot`` calls ``OriginResolver.resolve(...)`` at Order=300
to get origin, then evaluates the allow/deny list.

``OriginResolver`` Protocol default impl
``DenyByDefaultOriginResolver``: doesn't recognize any origin; all
results are ``None``; with ``default_deny_unresolved=True`` **everything
is denied** (safe default). M3.x Adapter wires real resolvers
(JWT / mTLS / gateway verification / internal service accounts).

Design points:

- **Order=300** after Statistic (200), before System (400); metrics
  collect first; unauthorized requests fail-fast.
- **default_deny_unresolved** True: resolver returns ``None`` → raise
  ``AuthorityDenied`` directly (not counted as metric hit, audit
  log separate).
- **untrusted fallback** ``X-Origin`` header via
  ``UntrustedHeaderOriginResolver``; **not** enabled by default;
  must be explicitly ``engine.add_resolver(...)``.
- **resolver config error** → Slot rejects + audit (no silent pass)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..engine.slot import ORDER_AUTHORITY, Slot
from ..errors import AuthorityDenied
from ..model.argument import InvocationArguments
from ..model.context import SentinelContext
from ..model.decision import SlotLease
from ..model.enums import BlockReason
from ..model.resource import Resource
from ..rules.authority import AuthorityRule


@runtime_checkable
class OriginResolver(Protocol):
    """中文
    ----
    Origin 解析器 Port。

    - ``resolve(context, args)`` 同步或协程;返回 origin 字符串或
      ``None``(无法解析)
    - 实现必须**不**抛异常;解析失败时返回 ``None`` + 记录内部错误
    - 任何 ``X-Origin`` 之类 header 解析器**必须**显式标注
      ``Untrusted`` 警告,提示"客户端自报身份"

    English
    --------
    Origin resolver Port.

    - ``resolve(context, args)`` sync or coroutine; returns origin
      string or ``None`` (unresolved).
    - Implementations **must not** raise; on failure return ``None`` +
      record internal error.
    - Any ``X-Origin`` header parser **must** explicitly mark
      ``Untrusted`` warning (client self-reported identity)."""

    def resolve(
        self,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> "str | None | Awaitable[str | None]":
        ...


class DenyByDefaultOriginResolver:
    """中文
    ----
    默认安全 resolver:任何 origin 都返回 ``None``。

    用于尚未配置真实 resolver 的 Engine;配合
    ``AuthorityRule.default_deny_unresolved=True`` → 全部拒绝。

    English
    --------
    Default safe resolver: returns ``None`` for all origins.

    Used by Engines without a real resolver; with
    ``AuthorityRule.default_deny_unresolved=True`` → all denied.
    """

    __slots__ = ()

    def resolve(
        self,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> "str | None":
        return None


class UntrustedHeaderOriginResolver:
    """中文
    ----
    从 HTTP header 读 origin(``X-Origin`` 默认)。

    **仅**作为"显式启用的不可信示例",**不**默认启用。任何启用都
    应该审计("客户端自报身份"风险):

    - 没有 JWT / mTLS / 网关验签的环境**不要**用
    - 用时必须配 ``ALLOW_LIST`` 限制可接受 origin 集合

    English
    --------
    Read origin from HTTP header (``X-Origin`` default).

    **Only** as "explicitly-enabled untrusted example"; **not**
    enabled by default. Any usage should be audited ("client self-
    reported identity" risk):

    - Do not use in environments without JWT / mTLS / gateway
      verification.
    - When used, must pair with ``ALLOW_LIST`` to limit acceptable
      origin set.
    """

    __slots__ = ("header_name",)

    def __init__(self, header_name: str = "X-Origin") -> None:
        self.header_name = header_name

    def resolve(
        self,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> "str | None":
        extra = context.extra or {}
        if not isinstance(extra, dict):
            return None
        headers = extra.get("headers", {})
        if not isinstance(headers, dict):
            return None
        v = headers.get(self.header_name)
        if isinstance(v, str) and v:
            return v
        return None


class AuthoritySlot(Slot):
    """中文
    ----
    AuthorityRule 黑白名单 Slot。

    用法::

        engine = SentinelEngine()
        engine.add_resolver(UntrustedHeaderOriginResolver())
        engine.add_slot(AuthoritySlot(rules_index=repo.current_index))

    English
    --------
    AuthorityRule allow/deny slot.

    Usage::

        engine = SentinelEngine()
        engine.add_resolver(UntrustedHeaderOriginResolver())
        engine.add_slot(AuthoritySlot(rules_index=repo.current_index))
    """

    @property
    def order(self) -> int:
        return ORDER_AUTHORITY

    def __init__(
        self,
        *,
        rules_index: Any = None,
        resolver: OriginResolver | None = None,
    ) -> None:
        self._rules_index = rules_index
        self._resolver: OriginResolver = resolver or DenyByDefaultOriginResolver()
        self._last_error: BaseException | None = None
        self._denied_unresolved: int = 0  # metric / 审计

    @property
    def last_error(self) -> BaseException | None:
        return self._last_error

    @property
    def denied_unresolved(self) -> int:
        """中文
        ----
        因 ``default_deny_unresolved`` 拒绝的次数(用于审计)。

        English
        --------
        Count of denials due to ``default_deny_unresolved`` (for audit).
        """
        return self._denied_unresolved

    def set_resolver(self, resolver: OriginResolver) -> None:
        """中文
        ----
        替换 resolver(Adapter 注入)。

        English
        --------
        Replace resolver (Adapter injection).
        """
        self._resolver = resolver

    def _resolve_rules(self, resource: Resource) -> list[AuthorityRule]:
        if self._rules_index is None:
            return []
        idx = (
            self._rules_index()
            if callable(self._rules_index)
            else self._rules_index
        )
        if idx is None:
            return []
        matched: list[AuthorityRule] = []
        seen: set[str] = set()
        for indexed in idx.find(resource.name):
            rule = indexed.rule
            if not isinstance(rule, AuthorityRule):
                continue
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            matched.append(rule)
        return matched

    def _resolve_origin(
        self, context: SentinelContext, args: InvocationArguments | None
    ) -> "str | None":
        result = self._resolver.resolve(context, args)
        # 协程 resolver: M2.5 占位
        if asyncio_iscoroutine(result):
            try:
                loop = asyncio_get_event_loop()
                if loop.is_running():
                    return None  # 已在 event loop, resolver 自己后续再处理
                result = loop.run_until_complete(result)  # type: ignore[arg-type]
            except RuntimeError:
                return None
        return result  # type: ignore[return-value]

    def enter(
        self,
        *,
        resource: Resource,
        context: SentinelContext,
        args: InvocationArguments | None,
    ) -> SlotLease:
        rules = self._resolve_rules(resource)
        if not rules:
            return _NoopAuthorityLease()
        # 解析 origin
        try:
            origin = self._resolve_origin(context, args)
        except Exception as e:
            self._last_error = e
            # resolver 抛错 → 拒绝 + 审计
            raise AuthorityDenied(
                f"AuthoritySlot: OriginResolver raised: {e}",
                resource=resource,
                rule_id="<resolver>",
                origin="<resolver-error>",
                retry_after=0.0,
            )
        if origin is None:
            # 无法解析: 按 default_deny_unresolved 决定
            if any(r.default_deny_unresolved for r in rules):
                self._denied_unresolved += 1
                raise AuthorityDenied(
                    "AuthoritySlot: origin unresolved (default_deny_unresolved=True)",
                    resource=resource,
                    rule_id="<unresolved>",
                    origin="<unresolved>",
                    retry_after=0.0,
                )
            return _NoopAuthorityLease()
        # 走规则判定
        for rule in rules:
            if not rule.is_allowed(origin):
                raise AuthorityDenied(
                    f"AuthorityRule {rule.rule_id!r}: origin {origin!r} "
                    f"rejected ({rule.strategy.value})",
                    resource=resource,
                    rule_id=rule.rule_id,
                    origin=origin,
                    retry_after=0.0,
                )
        return _NoopAuthorityLease()


def asyncio_iscoroutine(obj: Any) -> bool:
    """中文
    ----
    本地 helper:判断是否是协程(避免顶层 ``import asyncio``)。

    English
    --------
    Local helper: check coroutine (avoid top-level ``import asyncio``).
    """
    import asyncio
    return asyncio.iscoroutine(obj)


def asyncio_get_event_loop():
    """中文
    ----
    本地 helper:取 event loop。

    English
    --------
    Local helper: get event loop.
    """
    import asyncio
    return asyncio.get_event_loop()


@dataclass(slots=True)
class _NoopAuthorityLease:
    async def release(self) -> None:
        return None


__all__ = [
    "OriginResolver",
    "DenyByDefaultOriginResolver",
    "UntrustedHeaderOriginResolver",
    "AuthoritySlot",
    "_NoopAuthorityLease",
]
