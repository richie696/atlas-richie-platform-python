"""显式 JSON Schema 校验适配器的端口。

中文
----
`core` 不内嵌任何具体 JSON Schema 引擎；只暴露 `SchemaCompiler` /
`CompiledSchema` 两个 Protocol 端口，由外部适配器（如
`atlas-richie-mcp-schema-jsonschema`）实现。

- `CompiledSchema`：不可变、可在多次调用间复用的编译结果。
- `SchemaViolation`：与具体校验库解耦的校验问题描述。
- `SchemaCompiler`：把 `Mapping` 形态的 schema 编译为 `CompiledSchema`。
- `require_schema_compiler`：未注入编译器时抛 `CapabilityUnavailable`，
  强制业务方显式选择适配器。

English
--------
Ports for explicit JSON Schema validation adapters.

`core` does not embed any concrete JSON Schema engine; it only exposes
the `SchemaCompiler` / `CompiledSchema` Protocol ports, implemented by
external adapters (e.g. `atlas-richie-mcp-schema-jsonschema`).

- `CompiledSchema`: immutable, safe to reuse across invocations.
- `SchemaViolation`: validator-neutral violation description.
- `SchemaCompiler`: compile a `Mapping`-shaped schema into a
  `CompiledSchema`.
- `require_schema_compiler`: raise `CapabilityUnavailable` when no
  compiler is injected, forcing callers to pick an adapter explicitly.

Mirrors the adapter seam pattern in Java's
`atlas-richie-mcp-schema` module.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from atlas_richie.contracts import CapabilityUnavailable


@dataclass(frozen=True, slots=True)
class SchemaViolation:
    """中文
    ----
    传输安全的校验问题，**不暴露校验库特定对象**。

    English
    --------
    A transport-safe validation problem, without validator-specific
    objects.
    """

    instance_path: str
    schema_path: str
    message: str


class CompiledSchema(Protocol):
    """中文
    ----
    编译后的 schema，**不可变**，可在多次调用间安全复用。

    English
    --------
    Compiled schemas are immutable and safe to reuse across invocations.
    """

    def validate(self, value: Any) -> tuple[SchemaViolation, ...]: ...


class SchemaCompiler(Protocol):
    """中文
    ----
    适配器接缝 —— `core` 故意不导入任何具体 schema 引擎。

    English
    --------
    Adapter seam; core intentionally does not import a schema engine.
    """

    def compile(self, schema: Mapping[str, Any]) -> CompiledSchema: ...


def require_schema_compiler(compiler: SchemaCompiler | None) -> SchemaCompiler:
    """中文
    ----
    显式获取 schema 编译器；未注入时抛 `CapabilityUnavailable`，强制业务方选择适配器。

    Args:
        compiler: 已注入的编译器（或 `None`）。

    Returns:
        同一 `compiler` 引用。

    Raises:
        CapabilityUnavailable: 当 `compiler` 为 `None` 时。

    English
    --------
    Resolve a schema compiler explicitly; raise `CapabilityUnavailable`
    when none has been injected, forcing callers to pick an adapter.

    Args:
        compiler: the injected compiler (or `None`).

    Returns:
        the same `compiler` reference.

    Raises:
        CapabilityUnavailable: when `compiler` is `None`.
    """
    if compiler is None:
        raise CapabilityUnavailable("JSON Schema requires atlas-richie-mcp-schema-jsonschema or another explicit SchemaCompiler adapter")
    return compiler
