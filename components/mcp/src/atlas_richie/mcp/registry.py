"""MCP 注册表的原子不可变快照与显式变更通知。

中文
----
- `McpRegistrySnapshot`：revision 一次自增的不可变快照；四个 mapping 在
  `__post_init__` 中被 `MappingProxyType` 冻结，外部无法突变。
- `McpRegistryChange`：携带 `previous_revision` / `current_revision` 的轻量通知。
- `RegistryListener`：`Callable[[McpRegistryChange], None]`，server 在
  `_replace_registry` 成功后回调；监听器异常不会回滚已生效的快照。

设计动机：调用方（特别是缓存、schema 编译器）可以原子地"以快照"为粒度
获取当前可见的 tool / resource / template / prompt / completion 集合，
避免与并发注册读到的中间状态交互。

English
--------
Atomic immutable MCP registry snapshots and explicit change notifications.

- `McpRegistrySnapshot`: an immutable snapshot with a monotonically
  increasing `revision`; the four registry mappings are frozen via
  `MappingProxyType` in `__post_init__` so external callers cannot
  mutate them in place.
- `McpRegistryChange`: lightweight change notification carrying
  `previous_revision` / `current_revision`.
- `RegistryListener`: `Callable[[McpRegistryChange], None]`, invoked by
  the server after a successful `_replace_registry`; listener failures
  never roll back the now-effective snapshot.

Design motivation: callers (especially caches and schema compilers) can
read the currently visible tool / resource / template / prompt /
completion set atomically as a snapshot, never interacting with
half-applied state from a concurrent registration.

Mirrors `cn.richie696.component.mcp.server.tool.McpToolRegistrySnapshot`
(Java — same name, narrower scope since the Java side splits registry
by concern).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import PromptDescriptor, ResourceDescriptor, ResourceTemplateDescriptor, ToolDescriptor
    from .server import CompletionHandler


def _freeze(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class McpRegistrySnapshot:
    """中文
    ----
    不可变注册表快照；包含 `tools` / `resources` / `resource_templates` /
    `prompts` 四个 mapping + 可选的 `completion_handler`，并以 `revision`
    单调递增标识版本。

    构造时四个 mapping 会被 `MappingProxyType` 冻结，外部无法突变；
    `revision` 必须为非负整数。

    English
    --------
    Immutable registry snapshot holding `tools` / `resources` /
    `resource_templates` / `prompts` mappings and an optional
    `completion_handler`, versioned by a monotonically increasing
    `revision`.

    The four mappings are frozen via `MappingProxyType` at construction
    so external callers cannot mutate them in place; `revision` must be
    non-negative.
    """

    revision: int
    tools: Mapping[str, "ToolDescriptor"]
    resources: Mapping[str, "ResourceDescriptor"]
    resource_templates: Mapping[str, "ResourceTemplateDescriptor"]
    prompts: Mapping[str, "PromptDescriptor"]
    completion_handler: "CompletionHandler | None" = None

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("MCP registry revision must be non-negative")
        for name in ("tools", "resources", "resource_templates", "prompts"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class McpRegistryChange:
    """中文
    ----
    注册表变更通知；携带前后 `revision` 便于消费者感知版本跨度。

    English
    --------
    Registry change notification; carries the previous and current
    revisions so consumers can see the version span.
    """

    previous_revision: int
    current_revision: int


RegistryListener = Callable[[McpRegistryChange], None]
"""中文
----
注册表变更监听器协议；server 在 `_replace_registry` 成功后回调。

English
--------
Registry change listener protocol; invoked by the server after a
successful `_replace_registry`.
"""
