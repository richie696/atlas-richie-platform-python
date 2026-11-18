"""Masking service: the batch entry point for strings and nested mappings.

Ported from `cn.richie696.component.desensitize.core.service` (Java).

Not ported: `ObjectMaskingService` / `SafeLogSerializer` (reflection and JSON
serialization adapters) and the static `DesensitizeUtils` global binding — the
platform has no global runtime, so callers inject the service explicitly.
"""

from __future__ import annotations

from typing import Any, Protocol

from .model import MaskContext, MaskScene, MaskType
from .permission import DefaultMaskPermissionEvaluator, MaskPermissionEvaluator
from .properties import DesensitizeProperties
from .registry import MaskRuleRegistry, SensitiveKeyRegistry
from .strategies import MaskingStrategyRegistry

_MAX_MAP_DEPTH = 8


class MaskingService(Protocol):
    def mask(self, raw: str | None, mask_type: MaskType, scene: MaskScene = MaskScene.LOG) -> str | None: ...

    def mask_map(self, source: dict[str, Any] | None, scene: MaskScene = MaskScene.LOG) -> dict[str, Any] | None: ...


class DefaultMaskingService:
    """Applies global/scene switches and plaintext permissions before masking."""

    def __init__(
        self,
        properties: DesensitizeProperties | None = None,
        strategy_registry: MaskingStrategyRegistry | None = None,
        rule_registry: MaskRuleRegistry | None = None,
        sensitive_key_registry: SensitiveKeyRegistry | None = None,
        permission_evaluator: MaskPermissionEvaluator | None = None,
    ) -> None:
        self._properties = properties if properties is not None else DesensitizeProperties()
        self._strategy_registry = strategy_registry or MaskingStrategyRegistry()
        self._rule_registry = rule_registry or MaskRuleRegistry(self._properties)
        self._sensitive_key_registry = sensitive_key_registry or SensitiveKeyRegistry(self._properties)
        self._permission_evaluator = permission_evaluator or DefaultMaskPermissionEvaluator(self._properties)

    def mask(
        self,
        raw: str | None,
        mask_type: MaskType,
        scene: MaskScene = MaskScene.LOG,
        context: MaskContext | None = None,
    ) -> str | None:
        if raw is None:
            return None
        context = context if context is not None else MaskContext.of(scene)
        if not self._properties.enabled or not self._properties.is_scene_enabled(context.scene):
            return raw
        if not self._permission_evaluator.should_mask(context):
            return raw
        rule = self._rule_registry.to_rule(mask_type)
        return self._strategy_registry.require(mask_type).mask(raw, rule)

    def mask_map(
        self, source: dict[str, Any] | None, scene: MaskScene = MaskScene.LOG
    ) -> dict[str, Any] | None:
        if source is None:
            return None
        return self._mask_map(source, scene, 0, set())

    def _mask_map(
        self, source: dict[str, Any], scene: MaskScene, depth: int, ancestors: set[int]
    ) -> dict[str, Any]:
        """Recursive map masking, bounded against deep and cyclic graphs.

        A log serializer must terminate on self-referencing payloads. Java's
        `maskMap` recurses without a bound; here depth is capped and an ancestor
        mapping is replaced by a marker rather than expanded, so neither a cycle
        nor a very deep graph can hang the caller or leak unmasked content.
        """
        if depth > _MAX_MAP_DEPTH:
            return {"[max-depth]": "[max-depth]"}
        marker = id(source)
        if marker in ancestors:
            return {"[circular]": "[circular]"}
        ancestors = ancestors | {marker}
        result: dict[str, Any] = {}
        for key, value in source.items():
            if isinstance(value, str):
                mask_type = self._sensitive_key_registry.resolve(key, scene)
                result[key] = (
                    self.mask(value, mask_type, scene, MaskContext.of(scene, key, None))
                    if mask_type is not None
                    else value
                )
            elif isinstance(value, dict):
                result[key] = self._mask_map(value, scene, depth + 1, ancestors)
            elif isinstance(value, (list, tuple)):
                # Java maskMap 递归集合；列表内的 dict 同样含敏感字段。
                result[key] = type(value)(
                    self._mask_map(item, scene, depth + 1, ancestors)
                    if isinstance(item, dict)
                    else item
                    for item in value
                )
            else:
                result[key] = value
        return result


__all__ = ["DefaultMaskingService", "MaskingService"]
