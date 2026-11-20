"""Rule resolution and sensitive-key indexing.

Ported from `cn.richie696.component.desensitize.core.registry` (Java).

Field-type resolution is split in two: this module resolves the explicit
`properties.fields` mapping, while the annotation-driven path (Java's
`@Sensitive` reflection) is ported as dataclass field metadata and lives in
`support.py` + `serializer.py`.
"""

from __future__ import annotations

from .model import (
    MaskRule,
    MaskScene,
    MaskType,
    default_keep_left,
    default_keep_right,
    default_mask_length,
)
from .properties import DesensitizeProperties


def _class_key(declaring_class: type) -> str:
    """Python equivalent of Java's `Class.getName()` fully-qualified name."""
    return f"{declaring_class.__module__}.{declaring_class.__qualname__}"


class MaskRuleRegistry:
    """Turns a `MaskType` into a concrete rule, applying configured overrides."""

    def __init__(self, properties: DesensitizeProperties) -> None:
        self._properties = properties

    def resolve_field_type(
        self, declaring_class: type | None, field_name: str | None, scene: MaskScene
    ) -> MaskType | None:
        """Resolve a field's type from `properties.fields[class_fqn][field]`.

        `scene` is accepted for API parity; in Java it only filters the
        annotation-driven path, which is ported elsewhere (see `support.py`).
        """
        if declaring_class is None or field_name is None:
            return None
        class_rules = self._properties.fields.get(_class_key(declaring_class))
        if class_rules is None:
            return None
        return class_rules.get(field_name)

    def to_rule(self, mask_type: MaskType) -> MaskRule:
        type_rule = self._properties.type_rules.get(mask_type)
        keep_left = (
            type_rule.keep_left
            if type_rule is not None and type_rule.keep_left is not None
            else default_keep_left(mask_type)
        )
        keep_right = (
            type_rule.keep_right
            if type_rule is not None and type_rule.keep_right is not None
            else default_keep_right(mask_type)
        )
        mask_char = (
            type_rule.mask_char
            if type_rule is not None and type_rule.mask_char is not None
            else self._properties.default_mask_char
        )
        mask_length = (
            type_rule.mask_length
            if type_rule is not None and type_rule.mask_length is not None
            else default_mask_length(mask_type)
        )
        return MaskRule(mask_type, keep_left, keep_right, mask_char, None, mask_length)


def _normalize(source: dict[str, MaskType] | None) -> dict[str, MaskType]:
    return {key.lower(): value for key, value in (source or {}).items()}


def _merge(base: dict[str, MaskType], override: dict[str, MaskType] | None) -> dict[str, MaskType]:
    merged = dict(base)
    merged.update(_normalize(override))
    return merged


class SensitiveKeyRegistry:
    """Pre-computes per-scene sensitive-key maps; lookups are case-insensitive."""

    def __init__(self, properties: DesensitizeProperties) -> None:
        global_keys = _normalize(properties.sensitive_keys)
        self._global_keys = global_keys
        self._scene_keys: dict[MaskScene, dict[str, MaskType]] = {
            MaskScene.API_RESPONSE: _merge(global_keys, properties.api_response.sensitive_keys),
            MaskScene.LOG: _merge(global_keys, properties.log.sensitive_keys),
            # Java quirk preserved: AUDIT inherits the LOG overrides, not its own.
            MaskScene.AUDIT: _merge(global_keys, properties.log.sensitive_keys),
            MaskScene.EXCEPTION: _merge(global_keys, {}),
        }

    def resolve(self, key: str | None, scene: MaskScene) -> MaskType | None:
        if key is None:
            return None
        return self._scene_keys.get(scene, self._global_keys).get(key.lower())

    def keys_for_scene(self, scene: MaskScene) -> dict[str, MaskType]:
        return dict(self._scene_keys.get(scene, self._global_keys))


__all__ = ["MaskRuleRegistry", "SensitiveKeyRegistry"]
