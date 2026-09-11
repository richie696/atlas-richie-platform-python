"""Framework-neutral MCP API values and handler ports."""

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
    progress: float
    total: float | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.progress) or (self.total is not None and not isfinite(self.total)):
            raise ValueError("progress and total must be finite")
        if self.progress < 0 or (self.total is not None and self.total <= 0):
            raise ValueError("progress must be non-negative and total positive when present")


class ProgressReporter(Protocol):
    def report(self, update: ProgressUpdate) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Explicit per-invocation identity; raw credentials and HTTP objects stay outside core."""

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
    uri: str
    name: str
    read: Handler = field(repr=False, compare=False)
    description: str | None = None
    mime_type: str | None = None
    title: str | None = None
    required_scopes: frozenset[str] = frozenset()

    def public_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"uri": self.uri, "name": self.name}
        for source, target in ((self.title, "title"), (self.description, "description"), (self.mime_type, "mimeType")):
            if source:
                result[target] = source
        return result


@dataclass(frozen=True, slots=True)
class ResourceTemplateDescriptor:
    uri_template: str
    name: str
    description: str | None = None
    mime_type: str | None = None

    def public_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"uriTemplate": self.uri_template, "name": self.name}
        if self.description:
            result["description"] = self.description
        if self.mime_type:
            result["mimeType"] = self.mime_type
        return result


@dataclass(frozen=True, slots=True)
class PromptDescriptor:
    name: str
    render: Handler = field(repr=False, compare=False)
    description: str | None = None
    title: str | None = None
    arguments: tuple[Mapping[str, Any], ...] = ()
    required_scopes: frozenset[str] = frozenset()

    def public_json(self) -> dict[str, Any]:
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
    values: tuple[str, ...]
    total: int | None = None
    has_more: bool | None = None

    def __post_init__(self) -> None:
        if len(self.values) > 100 or (self.total is not None and self.total < 0):
            raise ValueError("completion values must contain <=100 items and total must be non-negative")

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"values": list(self.values)}
        if self.total is not None:
            result["total"] = self.total
        if self.has_more is not None:
            result["hasMore"] = self.has_more
        return result


@dataclass(frozen=True, slots=True)
class InputRequired:
    """Explicit multi-round result; request state is opaque and owned by the embedding app."""

    input_requests: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    request_state: str | None = None

    def __post_init__(self) -> None:
        if not self.input_requests and not self.request_state:
            raise ValueError("input_required requires input_requests or request_state")

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"resultType": "input_required"}
        if self.input_requests:
            result["inputRequests"] = {key: dict(value) for key, value in self.input_requests.items()}
        if self.request_state:
            result["requestState"] = self.request_state
        return result
