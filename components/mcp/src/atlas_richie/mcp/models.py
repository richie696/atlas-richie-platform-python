"""MCP API 值与 handler 端口，与具体框架无关。

中文
----
定义 MCP 业务侧稳定使用的值对象与 handler 协议；**不绑定**任何具体 Web
框架 / ORM / 传输。

- **进度**：`ProgressUpdate` / `ProgressReporter`。
- **上下文**：`ToolContext` —— 携带 principal / tenant / scope / 取消 / 截止
  / traceId / 进度回报，原始凭据 / HTTP 对象**留在 core 之外**。
- **描述符**：`ToolDescriptor` / `ResourceDescriptor` /
  `ResourceTemplateDescriptor` / `PromptDescriptor`。
- **结果**：`CompletionResult`（最多 100 项，`total >= 0`）/ `InputRequired`
  （多轮交互结果，request_state 由调用方持有）。
- **Handler 类型别名**：`Handler = Callable[..., object | Awaitable[object]]`。

所有公开 dataclass 均 `@dataclass(frozen=True, slots=True)` —— 不可变 +
内存紧凑。

English
--------
Framework-neutral MCP API values and handler ports.

Stable value objects and handler protocols for MCP business code;
**transport- / framework-neutral** (no Web framework, ORM, or
transport in this module).

- **Progress**: `ProgressUpdate`, `ProgressReporter`.
- **Context**: `ToolContext` — carries principal / tenant / scope /
  cancellation / deadline / traceId / progress reporter. **Raw
  credentials and HTTP objects stay outside core.**
- **Descriptors**: `ToolDescriptor`, `ResourceDescriptor`,
  `ResourceTemplateDescriptor`, `PromptDescriptor`.
- **Results**: `CompletionResult` (max 100 items, `total >= 0`),
  `InputRequired` (multi-round interaction result; `request_state` is
  opaque, owned by the embedding app).
- **Handler type alias**: `Handler = Callable[..., object |
  Awaitable[object]]`.

Every public dataclass is `@dataclass(frozen=True, slots=True)` —
immutable and memory-efficient.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from typing import Any, Protocol

from .cancellation import CancellationToken

Handler = Callable[..., object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """中文
    ----
    一次进度上报：`progress` 必须为有限非负数；`total` 在存在时必须为有限正数。

    English
    --------
    A progress update. `progress` must be finite and non-negative;
    `total`, if present, must be finite and strictly positive.
    """

    progress: float
    total: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.progress) or (self.total is not None and not isfinite(self.total)):
            raise ValueError("progress and total must be finite")
        if self.progress < 0 or (self.total is not None and self.total <= 0):
            raise ValueError("progress must be non-negative and total positive when present")


class ProgressReporter(Protocol):
    """中文
    ----
    业务侧进度回报端口；通过 `ToolContext.progress` 注入，调用方
    `await report(update)` 或 `report(update)` 同步调用。

    English
    --------
    Progress reporter port; injected via `ToolContext.progress` and
    invoked by tool implementations (sync or async).
    """

    def report(self, update: ProgressUpdate) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolContext:
    """中文
    ----
    显式的 per-invocation 身份 / 横切信息；**原始凭据 / HTTP 对象不在 core 中**。

    English
    --------
    Explicit per-invocation identity; raw credentials and HTTP objects
    stay outside core.
    """

    principal_id: str | None = None
    principal_kind: str | None = None
    tenant_id: str | None = None
    granted_scopes: frozenset[str] = frozenset()
    client_info: Mapping[str, Any] = field(default_factory=dict)
    request_state: str | None = None
    input_responses: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    cancellation: CancellationToken = field(default_factory=CancellationToken, repr=False, compare=False)
    deadline: datetime | None = None
    trace_id: str | None = None
    progress: ProgressReporter | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """中文
    ----
    不可变 Tool 描述：name / title / description / function / scopes /
    input-output schema / annotations / 编译后 schema。

    `function` 和编译后 schema 不参与 `repr` / `compare`，避免噪音。

    English
    --------
    Immutable tool descriptor: name, title, description, function,
    scopes, input / output schemas, annotations, and compiled
    schemas. The `function` and compiled schemas are excluded from
    `repr` and equality.
    """

    name: str
    description: str
    function: Handler = field(repr=False, compare=False)
    required_scopes: frozenset[str] = frozenset()
    input_schema: Mapping[str, Any] | None = None
    output_schema: Mapping[str, Any] | None = None
    title: str | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)
    compiled_input_schema: object | None = field(default=None, repr=False, compare=False)
    compiled_output_schema: object | None = field(default=None, repr=False, compare=False)

    def public_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 MCP `tools/list` 协议暴露的 JSON 形态（仅公开字段，function 与
        compiled schema 永不出现）。

        Returns:
            含 `name` / `description` / 可选 `title` / `inputSchema` /
            `outputSchema` / `annotations` 的 dict。

        English
        --------
        Render to the JSON shape exposed by the `tools/list` protocol
        (public fields only; the function and compiled schemas never
        appear on the wire).

        Returns:
            a dict with `name`, `description`, and optional `title`,
            `inputSchema`, `outputSchema`, `annotations`.
        """
        result: dict[str, Any] = {"name": self.name, "description": self.description}
        if self.title:
            result["title"] = self.title
        if self.input_schema is not None:
            result["inputSchema"] = dict(self.input_schema)
        if self.output_schema is not None:
            result["outputSchema"] = dict(self.output_schema)
        if self.annotations:
            result["annotations"] = dict(self.annotations)
        return result


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    """中文
    ----
    不可变资源描述：uri / name / `read` handler / description /
    mime_type / title / required_scopes。

    `read` 不参与 `repr` / `compare`。

    English
    --------
    Immutable resource descriptor: uri, name, `read` handler,
    description, mime_type, title, required_scopes. The `read` handler
    is excluded from `repr` and equality.
    """

    uri: str
    name: str
    read: Handler = field(repr=False, compare=False)
    description: str | None = None
    mime_type: str | None = None
    title: str | None = None
    required_scopes: frozenset[str] = frozenset()

    def public_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 `resources/list` 协议 JSON（公开字段，handler 永不暴露）。

        English
        --------
        Render to the JSON exposed by the `resources/list` protocol
        (public fields only; the handler never appears on the wire).
        """
        result: dict[str, Any] = {"uri": self.uri, "name": self.name}
        for source, target in ((self.title, "title"), (self.description, "description"), (self.mime_type, "mimeType")):
            if source:
                result[target] = source
        return result


@dataclass(frozen=True, slots=True)
class ResourceTemplateDescriptor:
    """中文
    ----
    资源模板描述（`resources/templates/list` 协议暴露的元数据），只描述
    如何发现/构造，不解析 URI。

    English
    --------
    Resource template descriptor exposed by the
    `resources/templates/list` protocol. Describes how to discover /
    construct, but does not resolve URIs.
    """

    uri_template: str
    name: str
    description: str | None = None
    mime_type: str | None = None

    def public_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 `resources/templates/list` 协议 JSON 形态。

        English
        --------
        Render to the JSON shape exposed by the
        `resources/templates/list` protocol.
        """
        result: dict[str, Any] = {"uriTemplate": self.uri_template, "name": self.name}
        if self.description:
            result["description"] = self.description
        if self.mime_type:
            result["mimeType"] = self.mime_type
        return result


@dataclass(frozen=True, slots=True)
class PromptDescriptor:
    """中文
    ----
    不可变 prompt 描述：name / `render` handler / title / description /
    arguments / required_scopes。

    `render` 不参与 `repr` / `compare`。

    English
    --------
    Immutable prompt descriptor: name, `render` handler, title,
    description, arguments, required_scopes. The `render` handler is
    excluded from `repr` and equality.
    """

    name: str
    render: Handler = field(repr=False, compare=False)
    description: str | None = None
    title: str | None = None
    arguments: tuple[Mapping[str, Any], ...] = ()
    required_scopes: frozenset[str] = frozenset()

    def public_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 `prompts/list` 协议 JSON 形态（公开字段）。

        English
        --------
        Render to the JSON shape exposed by the `prompts/list`
        protocol (public fields only).
        """
        result: dict[str, Any] = {"name": self.name}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if self.arguments:
            result["arguments"] = [dict(item) for item in self.arguments]
        return result


@dataclass(frozen=True, slots=True)
class CompletionResult:
    """中文
    ----
    `completion/complete` 协议结果：最多 100 项；`total` 不可为负；`has_more`
    仅在调用方希望携带分页提示时设置。

    English
    --------
    `completion/complete` protocol result: at most 100 items; `total`
    must be non-negative; `has_more` is set only when the caller wants
    to carry a pagination hint.
    """

    values: tuple[str, ...]
    total: int | None = None
    has_more: bool | None = None

    def __post_init__(self) -> None:
        if len(self.values) > 100 or (self.total is not None and self.total < 0):
            raise ValueError("completion values must contain <=100 items and total must be non-negative")

    def as_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 `completion/complete` 协议结果 JSON 形态。

        English
        --------
        Render to the JSON shape exposed by the `completion/complete`
        protocol.
        """
        result: dict[str, Any] = {"values": list(self.values)}
        if self.total is not None:
            result["total"] = self.total
        if self.has_more is not None:
            result["hasMore"] = self.has_more
        return result


@dataclass(frozen=True, slots=True)
class InputRequired:
    """中文
    ----
    显式多轮交互结果；`request_state` 是不透明 token，由嵌入应用持有，
    `core` 不解读（除非 `MrtStateBinding` 注入后才会签名 / 校验）。

    构造时 `input_requests` 与 `request_state` 至少要有一个非空。

    English
    --------
    Explicit multi-round result; `request_state` is an opaque token
    owned by the embedding app and not interpreted by `core` (unless
    an `MrtStateBinding` is injected, in which case it is signed /
    verified).

    At least one of `input_requests` / `request_state` must be present.
    """

    input_requests: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    request_state: str | None = None

    def __post_init__(self) -> None:
        if not self.input_requests and not self.request_state:
            raise ValueError("input_required requires input_requests or request_state")

    def as_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 `resultType=input_required` 协议结果 JSON 形态。

        English
        --------
        Render to the JSON shape exposed as `resultType=input_required`.
        """
        result: dict[str, Any] = {"resultType": "input_required"}
        if self.input_requests:
            result["inputRequests"] = {key: dict(value) for key, value in self.input_requests.items()}
        if self.request_state:
            result["requestState"] = self.request_state
        return result
