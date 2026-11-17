"""Plain configuration object replacing the Spring `@ConfigurationProperties` class.

Only the fields the core actually consumes are ported. The log/exception regex
fallback settings belong to the logging adapter and are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import MaskScene, MaskType, default_keep_left, default_keep_right, default_mask_length


@dataclass
class TypeRule:
    keep_left: int | None = None
    keep_right: int | None = None
    mask_length: int | None = None
    mask_char: str | None = None


@dataclass
class Permission:
    enabled: bool = False
    plain_text_roles: set[str] = field(default_factory=set)


@dataclass
class SceneOverride:
    sensitive_keys: dict[str, MaskType] = field(default_factory=dict)


def _default_scenes() -> dict[str, bool]:
    return {scene.key: True for scene in MaskScene}


def _default_type_rules() -> dict[MaskType, TypeRule]:
    return {
        mask_type: TypeRule(
            keep_left=default_keep_left(mask_type),
            keep_right=default_keep_right(mask_type),
            mask_length=default_mask_length(mask_type),
            mask_char=None,
        )
        for mask_type in MaskType
    }


@dataclass
class DesensitizeProperties:
    enabled: bool = True
    default_mask_char: str = "*"
    scenes: dict[str, bool] = field(default_factory=_default_scenes)
    permission: Permission = field(default_factory=Permission)
    sensitive_keys: dict[str, MaskType] = field(default_factory=dict)
    type_rules: dict[MaskType, TypeRule] = field(default_factory=_default_type_rules)
    fields: dict[str, dict[str, MaskType]] = field(default_factory=dict)
    api_response: SceneOverride = field(default_factory=SceneOverride)
    log: SceneOverride = field(default_factory=SceneOverride)

    def is_scene_enabled(self, scene: MaskScene) -> bool:
        value = self.scenes.get(scene.key)
        return value is None or value


__all__ = ["DesensitizeProperties", "Permission", "SceneOverride", "TypeRule"]
