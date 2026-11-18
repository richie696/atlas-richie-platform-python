"""Log-safe serialization: object graphs, maps and collections.

Ported from `SafeLogSerializer` / `ObjectMaskingService` (Java). Depth is capped
at 8 like the Java `MAX_DEPTH`, which also bounds cyclic object graphs.

Two deliberate, security-driven deviations from Java are documented inline:
string escaping produces valid JSON, and the caller's scene is propagated into
nested values instead of being silently replaced by LOG.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any, Protocol

from .model import MaskContext, MaskScene, MaskType
from .registry import MaskRuleRegistry
from .service import MaskingService
from .support import is_transient, marker_of

MAX_DEPTH = 8
_DEPTH_PLACEHOLDER = "[max-depth]"


def _quote(value: str) -> str:
    """JSON-escape a string.

    Deviation: Java's hand-rolled `quote` escapes only `" \\ \\n \\r \\t`, leaving
    other control characters raw and emitting invalid JSON. A log serializer must
    produce parseable output, so this uses proper JSON escaping.
    """
    return json.dumps(value, ensure_ascii=False)


class ObjectMaskingService(Protocol):
    def to_safe_json(
        self, value: Any, scene: MaskScene = MaskScene.LOG
    ) -> str: ...

    def to_safe_string(self, mapping: Mapping[str, Any] | None) -> str: ...


class SafeLogSerializer:
    def __init__(
        self,
        masking_service: MaskingService,
        rule_registry: MaskRuleRegistry,
        *,
        max_depth: int = MAX_DEPTH,
    ) -> None:
        self._masking = masking_service
        self._rules = rule_registry
        self._max_depth = max_depth

    def to_safe_json(self, value: Any, scene: MaskScene = MaskScene.LOG) -> str:
        return self._serialize(value, scene, 0)

    def to_safe_string(self, mapping: Mapping[str, Any] | None) -> str:
        if mapping is None:
            return "null"
        masked = self._masking.mask_map(dict(mapping), MaskScene.LOG)
        return self._write_map(masked or {}, MaskScene.LOG, 0)

    def _serialize(self, value: Any, scene: MaskScene, depth: int) -> str:
        if value is None:
            return "null"
        if depth > self._max_depth:
            return _quote(_DEPTH_PLACEHOLDER)
        if isinstance(value, str):
            return _quote(value)
        if isinstance(value, bool):  # before int: bool is an int subclass in Python
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, Mapping):
            masked = self._masking.mask_map(dict(value), scene)
            return self._write_map(masked or {}, scene, depth)
        if isinstance(value, (list, tuple, set, frozenset)):
            return self._write_array(value, scene, depth)
        return self._write_bean(value, scene, depth)

    def _write_map(self, mapping: Mapping[str, Any], scene: MaskScene, depth: int) -> str:
        parts = [
            f"{_quote(str(key))}:{self._serialize(value, scene, depth + 1)}"
            for key, value in mapping.items()
        ]
        return "{" + ",".join(parts) + "}"

    def _write_array(self, values: Any, scene: MaskScene, depth: int) -> str:
        return "[" + ",".join(self._serialize(v, scene, depth + 1) for v in values) + "]"

    def _write_bean(self, bean: Any, scene: MaskScene, depth: int) -> str:
        parts: list[str] = []
        for name, value, declaring_class, marker in self._fields_of(bean):
            if isinstance(value, str):
                mask_type = self._resolve_field_type(declaring_class, name, scene, marker)
                if mask_type is not None:
                    context = MaskContext.of(scene, name, declaring_class)
                    value = self._masking.mask(value, mask_type, scene, context)
                parts.append(f"{_quote(name)}:{_quote(value if value is not None else '')}")
            else:
                parts.append(f"{_quote(name)}:{self._serialize(value, scene, depth + 1)}")
        return "{" + ",".join(parts) + "}"

    @staticmethod
    def _fields_of(bean: Any):
        """Yield (name, value, declaring_class, marker) for serializable fields."""
        cls = type(bean)
        if dataclasses.is_dataclass(bean):
            for f in dataclasses.fields(bean):
                if is_transient(f):
                    continue
                # ClassVar and KW_ONLY are not instance fields; annotations may be
                # strings when the declaring module uses `from __future__ import annotations`.
                annotation = f.type if isinstance(f.type, str) else str(f.type)
                if annotation.startswith("ClassVar") or "ClassVar" in annotation:
                    continue
                if f.type is dataclasses.KW_ONLY or annotation == "KW_ONLY":
                    continue
                yield f.name, getattr(bean, f.name, None), cls, marker_of(f)
            return
        slots = getattr(cls, "__slots__", ())
        if slots:
            for name in slots:
                yield name, getattr(bean, name, None), cls, None
            return
        instance_dict = getattr(bean, "__dict__", None)
        if instance_dict:
            for name, value in instance_dict.items():
                yield name, value, cls, None

    def _resolve_field_type(
        self, declaring_class: type, name: str, scene: MaskScene, marker: Any
    ) -> MaskType | None:
        if marker is not None and marker.applies_to(scene):
            return marker.type
        return self._rules.resolve_field_type(declaring_class, name, scene)


class DefaultObjectMaskingService:
    """Thin facade over `SafeLogSerializer`, matching the Java service shape."""

    def __init__(self, serializer: SafeLogSerializer) -> None:
        self._serializer = serializer

    def to_safe_json(
        self, value: Any, scene: MaskScene = MaskScene.LOG
    ) -> str:
        """JSON for a scene; the API_RESPONSE scene un-cloaks response payloads."""
        return self._serializer.to_safe_json(value, scene)

    def to_safe_string(self, mapping: Mapping[str, Any] | None) -> str:
        return self._serializer.to_safe_string(mapping)


class SensitiveLogArg:
    """A single sensitive value for interpolation into a log message.

    Deviation: Java's `toString()` returns the RAW value and relies on a Logback
    turbo filter to mask it. Python's logging has no such interception, so
    returning raw here would leak credentials. `__str__` therefore masks, using
    the injected service or a default one — safe by construction.
    """

    __slots__ = ("_value", "_type", "_service")

    def __init__(self, value: str | None, mask_type: MaskType, service: MaskingService | None = None) -> None:
        self._value = value
        self._type = mask_type
        self._service = service

    @classmethod
    def of(cls, value: str | None, mask_type: MaskType, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, mask_type, service)

    @classmethod
    def phone(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.PHONE, service)

    @classmethod
    def id_card(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.ID_CARD, service)

    @classmethod
    def email(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.EMAIL, service)

    @classmethod
    def bank_card(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.BANK_CARD, service)

    @classmethod
    def name(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.NAME, service)

    @classmethod
    def address(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.ADDRESS, service)

    @classmethod
    def password(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.PASSWORD, service)

    @classmethod
    def api_key(cls, value: str | None, service: MaskingService | None = None) -> SensitiveLogArg:
        return cls(value, MaskType.API_KEY, service)

    @property
    def raw_value(self) -> str | None:
        """Explicit access to the unmasked value; never used by `__str__`."""
        return self._value

    @property
    def mask_type(self) -> MaskType:
        return self._type

    def __str__(self) -> str:
        if self._value is None:
            return "null"
        service = self._service
        if service is None:
            from .service import DefaultMaskingService

            service = DefaultMaskingService()
        masked = service.mask(self._value, self._type, MaskScene.LOG)
        return masked if masked is not None else "null"

    def __repr__(self) -> str:
        return f"SensitiveLogArg({self._type.value}, masked)"


__all__ = [
    "MAX_DEPTH",
    "DefaultObjectMaskingService",
    "ObjectMaskingService",
    "SafeLogSerializer",
    "SensitiveLogArg",
]
