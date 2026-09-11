"""Ports for explicit JSON Schema validation adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from atlas_richie.contracts import CapabilityUnavailable


@dataclass(frozen=True, slots=True)
class SchemaViolation:
    """A transport-safe validation problem, without validator-specific objects."""

    instance_path: str
    schema_path: str
    message: str


class CompiledSchema(Protocol):
    """Compiled schemas are immutable and safe to reuse across invocations."""

    def validate(self, value: Any) -> tuple[SchemaViolation, ...]: ...


class SchemaCompiler(Protocol):
    """Adapter seam; core intentionally does not import a schema engine."""

    def compile(self, schema: Mapping[str, Any]) -> CompiledSchema: ...


def require_schema_compiler(compiler: SchemaCompiler | None) -> SchemaCompiler:
    if compiler is None:
        raise CapabilityUnavailable("JSON Schema requires atlas-richie-mcp-schema-jsonschema or another explicit SchemaCompiler adapter")
    return compiler
