"""Atomic immutable MCP registry snapshots and explicit change notifications."""

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
    previous_revision: int
    current_revision: int


RegistryListener = Callable[[McpRegistryChange], None]
