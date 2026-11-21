"""Immutable masking contracts: types, scenes, rules and context.

Ported from `cn.richie696.component.desensitize.core.model` (Java).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MaskType(StrEnum):
    PHONE = "PHONE"
    ID_CARD = "ID_CARD"
    EMAIL = "EMAIL"
    BANK_CARD = "BANK_CARD"
    NAME = "NAME"
    ADDRESS = "ADDRESS"
    PASSWORD = "PASSWORD"
    API_KEY = "API_KEY"
    CUSTOM = "CUSTOM"


class MaskScene(StrEnum):
    API_RESPONSE = "API_RESPONSE"
    LOG = "LOG"
    AUDIT = "AUDIT"
    EXCEPTION = "EXCEPTION"

    @property
    def key(self) -> str:
        """Kebab-case configuration key, matching the Java properties binding."""
        return self.value.lower().replace("_", "-")


_KEEP_LEFT = {
    MaskType.PHONE: 3,
    MaskType.ID_CARD: 6,
    MaskType.BANK_CARD: 4,
    MaskType.NAME: 1,
    MaskType.ADDRESS: 6,
    MaskType.EMAIL: 0,
    MaskType.PASSWORD: 0,
    MaskType.CUSTOM: 0,
    MaskType.API_KEY: 4,
}

_KEEP_RIGHT = {
    MaskType.PHONE: 4,
    MaskType.BANK_CARD: 4,
    MaskType.ID_CARD: 4,
    MaskType.NAME: 0,
    MaskType.ADDRESS: 0,
    MaskType.EMAIL: 0,
    MaskType.PASSWORD: 0,
    MaskType.CUSTOM: 0,
    MaskType.API_KEY: 4,
}


def default_keep_left(mask_type: MaskType) -> int:
    return _KEEP_LEFT[mask_type]


def default_keep_right(mask_type: MaskType) -> int:
    return _KEEP_RIGHT[mask_type]


def default_mask_length(mask_type: MaskType) -> int | None:
    """`None` means "emit as many mask characters as were actually replaced"."""
    return 4 if mask_type is MaskType.API_KEY else None


@dataclass(frozen=True, slots=True)
class MaskRule:
    """One masking rule, mirroring Java's `MaskRule` record.

    `custom_strategy` mirrors Java's `MaskRule.customStrategy`: it carries the
    name of a caller-supplied strategy for `MaskType.CUSTOM`. The parameter is
    carried, not resolved — Java routes `CUSTOM` by type as well and reads the
    parameter from the rule (its own lookup chain is planned for V2), so the
    Python side does the same: register a `MaskingStrategy` whose `supports`
    returns True for `MaskType.CUSTOM` and it masks every `CUSTOM` rule.
    """

    type: MaskType
    keep_left: int
    keep_right: int
    mask_char: str
    custom_strategy: str | None = None
    mask_length: int | None = None

    @classmethod
    def of(cls, mask_type: MaskType, mask_char: str = "*") -> MaskRule:
        return cls(
            mask_type,
            default_keep_left(mask_type),
            default_keep_right(mask_type),
            mask_char,
            None,
            default_mask_length(mask_type),
        )


@dataclass(frozen=True, slots=True)
class MaskContext:
    scene: MaskScene
    field_name: str | None = None
    declaring_class: type | None = None
    roles: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, scene: MaskScene, field_name: str | None = None, declaring_class: type | None = None) -> MaskContext:
        return cls(scene, field_name, declaring_class, frozenset())

    def with_roles(self, roles: frozenset[str] | set[str] | None) -> MaskContext:
        return MaskContext(
            self.scene, self.field_name, self.declaring_class, frozenset(roles or ())
        )


__all__ = [
    "MaskContext",
    "MaskRule",
    "MaskScene",
    "MaskType",
    "default_keep_left",
    "default_keep_right",
    "default_mask_length",
]
