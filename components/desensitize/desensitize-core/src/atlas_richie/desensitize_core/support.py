"""Field-level sensitivity markers for dataclass payloads.

Java marks fields with the `@Sensitive` annotation and resolves them by
reflection. Python has no equivalent runtime annotation, so the marker lives in
dataclass field metadata:

    @dataclass
    class User:
        phone: str = sensitive_field(MaskType.PHONE)
        email: str = sensitive_field(MaskType.EMAIL, scenes=(MaskScene.LOG,))

`ClassVar` fields and fields marked `transient` are skipped, mirroring Java's
skip of static and transient fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .model import MaskScene, MaskType

_METADATA_KEY = "sensitive"
_TRANSIENT_KEY = "transient"


@dataclass(frozen=True, slots=True)
class Sensitive:
    """Field marker: which mask type applies, and in which scenes."""

    type: MaskType
    scenes: tuple[MaskScene, ...] = (MaskScene.API_RESPONSE, MaskScene.LOG)
    custom_strategy: str = ""

    def applies_to(self, scene: MaskScene) -> bool:
        return scene in self.scenes


def sensitive_field(
    mask_type: MaskType,
    scenes: tuple[MaskScene, ...] = (MaskScene.API_RESPONSE, MaskScene.LOG),
    **kwargs: Any,
):
    """`dataclasses.field` with a sensitivity marker attached."""
    metadata = dict(kwargs.pop("metadata", {}) or {})
    metadata[_METADATA_KEY] = Sensitive(mask_type, tuple(scenes))
    return field(metadata=metadata, **kwargs)


def transient_field(**kwargs: Any):
    """A field excluded from safe serialization (Java's `transient`)."""
    metadata = dict(kwargs.pop("metadata", {}) or {})
    metadata[_TRANSIENT_KEY] = True
    return field(metadata=metadata, **kwargs)


def marker_of(dataclass_field) -> Sensitive | None:
    return (dataclass_field.metadata or {}).get(_METADATA_KEY)


def is_transient(dataclass_field) -> bool:
    return bool((dataclass_field.metadata or {}).get(_TRANSIENT_KEY))


__all__ = [
    "Sensitive",
    "is_transient",
    "marker_of",
    "sensitive_field",
    "transient_field",
]
