"""Local-only JSON Schema Draft 2020-12 compiler."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from atlas_richie.contracts import ValidationError
from atlas_richie.mcp.schema import SchemaViolation


class JsonSchemaCompiler:
    """Compile only self-contained schemas; remote resolution is forbidden by design."""

    def compile(self, schema: Mapping[str, Any]) -> "JsonSchema":
        frozen = _copy_json(schema)
        _reject_external_references(frozen)
        try:
            Draft202012Validator.check_schema(frozen)
        except SchemaError as error:
            raise ValidationError(f"invalid Draft 2020-12 schema: {error.message}") from error
        return JsonSchema(Draft202012Validator(frozen, format_checker=FormatChecker()))


@dataclass(frozen=True, slots=True)
class JsonSchema:
    _validator: Draft202012Validator

    def validate(self, value: Any) -> tuple[SchemaViolation, ...]:
        errors = sorted(self._validator.iter_errors(value), key=lambda error: (list(error.absolute_path), error.message))
        return tuple(
            SchemaViolation(_pointer(error.absolute_path), _pointer(error.absolute_schema_path), error.message)
            for error in errors
        )


def _reject_external_references(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and isinstance(item, str) and not item.startswith("#"):
                raise ValidationError("external JSON Schema references are not permitted")
            _reject_external_references(item)
    elif isinstance(value, list):
        for item in value:
            _reject_external_references(item)


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_copy_json(item) for item in value]
    return value


def _pointer(parts: Any) -> str:
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/" + "/".join(escaped) if parts else ""
