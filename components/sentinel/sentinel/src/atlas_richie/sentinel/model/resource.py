"""Sentinel 资源模型。

中文
----
资源是 Sentinel 的最小受保护单元,所有规则、流控、熔断都绑定在资源上。
`Resource` 是不可变的 frozen dataclass,通过 `name` 字符串标识;`kind` 决定
是否触发 SystemSlot / PoolGuard;`traffic_type` 决定流量方向(INBOUND / OUTBOUND /
INTERNAL)。

English
--------
Sentinel resource model — the smallest protected unit. A ``Resource`` is
identified by a ``name`` and classified by ``kind`` (which decides whether
``SystemSlot`` / ``PoolGuard`` apply) and ``traffic_type`` (which decides
whether the resource is an inbound endpoint, an outbound dependency, or
an internal call)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResourceKind(StrEnum):
    """中文
    ----
    资源分类。决定是否触发 SystemSlot / PoolGuard:

    - COMMON — 业务资源,既可入站也可出站
    - INBOUND — 入口流量(API endpoint / RPC server),触发 SystemSlot
    - OUTBOUND — 出站依赖(HTTP / DB / RPC client),触发 PoolGuard
    - INTERNAL — 进程内调用,既不触发 SystemSlot 也不触发 PoolGuard

    English
    --------
    Resource kind — decides whether ``SystemSlot`` / ``PoolGuard`` apply.

    - ``COMMON`` — generic business resource, may be inbound or outbound.
    - ``INBOUND`` — ingress (API endpoint / RPC server); subject to
      ``SystemSlot`` (CPU/load/QPS protection).
    - ``OUTBOUND`` — egress (HTTP / DB / RPC client); subject to
      ``PoolGuard`` (connection pool + concurrency cap).
    - ``INTERNAL`` — in-process; neither ``SystemSlot`` nor ``PoolGuard``
      applies.
    """

    COMMON = "common"
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class TrafficType(StrEnum):
    """中文
    ----
    流量方向。独立于 ``ResourceKind`` 因为同一个资源可能在不同调用路径上
    表现为不同方向(如 "GET /orders" 在网关侧是 INBOUND,在订单服务内部调用
    时是 INTERNAL)。

    - INBOUND — 服务入口
    - OUTBOUND — 出站依赖
    - INTERNAL — 进程内

    English
    --------
    Traffic direction. Independent of ``ResourceKind`` because the same
    resource can appear on multiple call paths (e.g. ``GET /orders`` is
    ``INBOUND`` at the gateway but ``INTERNAL`` when invoked from another
    service within the same process).
    """

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class Resource:
    """中文
    ----
    不可变资源描述。

    - `name` — 资源唯一名(同一 name 视为同一资源,共享所有规则)
    - `kind` — 资源分类(默认 ``COMMON``)
    - `traffic_type` — 流量方向(默认 ``INBOUND``)
    - `attrs` — 任意附加属性(如 ``{"method": "GET", "path": "/orders"}``)

    `attrs` 在构造时浅拷贝为 `dict[str, str]`,避免外部 mutation 影响
    资源身份;`__post_init__` 校验 value 类型(只接受 str)。

    English
    --------
    Immutable resource descriptor.

    - ``name`` — unique name (same name ⇒ same resource, shares all rules).
    - ``kind`` — resource kind (default ``COMMON``).
    - ``traffic_type`` — traffic direction (default ``INBOUND``).
    - ``attrs`` — extra attributes (e.g. ``{"method": "GET",
      "path": "/orders"}``).

    ``attrs`` is shallow-copied to ``dict[str, str]`` on construction to
    prevent external mutation from changing the resource identity;
    ``__post_init__`` enforces that all values are strings.
    """

    name: str
    kind: ResourceKind = ResourceKind.COMMON
    traffic_type: TrafficType = TrafficType.INBOUND
    attrs: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Resource.name must be non-empty")
        # Reject mutable defaults: caller might pass a list/tuple by accident
        if not isinstance(self.attrs, frozenset):
            # Convert list/tuple/set of pairs to frozenset of tuples
            coerced = frozenset(
                (k, str(v)) for k, v in dict(self.attrs).items()
            )
            object.__setattr__(self, "attrs", coerced)

    def attr(self, key: str, default: str | None = None) -> str | None:
        """中文
        ----
        按 key 取属性;未命中返回 ``default``。

        English
        --------
        Look up an attribute by key; return ``default`` when missing.
        """
        for k, v in self.attrs:
            if k == key:
                return v
        return default

    def with_kind(self, kind: ResourceKind) -> "Resource":
        """中文
        ----
        返回新 ``Resource``,``kind`` 替换为给定值(其它字段不变)。

        English
        --------
        Return a new ``Resource`` with ``kind`` replaced (other fields
        unchanged).
        """
        return Resource(
            name=self.name,
            kind=kind,
            traffic_type=self.traffic_type,
            attrs=self.attrs,
        )


__all__ = ["Resource", "ResourceKind", "TrafficType"]
