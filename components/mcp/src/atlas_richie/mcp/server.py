"""MCP server facade, immutable registries, and the protocol invocation chain."""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Callable, Mapping
from threading import RLock
from typing import Any
from dataclasses import replace

from atlas_richie.contracts import ValidationError

from .cancellation import CancellationToken, McpInvocationCancelled
from .errors import McpError, ProtocolError, ToolExecutionError
from .invocation import McpAuditSink, McpInvocation, McpInvocationInterceptor, McpTraceSink, build_invocation_pipeline, invoke_handler
from .models import (
    CompletionResult,
    InputRequired,
    PromptDescriptor,
    ResourceDescriptor,
    ResourceTemplateDescriptor,
    ToolContext,
    ToolDescriptor,
)
from .mrtr import MrtRequestStateError, MrtStateBinding
from .protocol import DEFAULT_DIALECT, Implementation, McpDialect, Request, failure, success
from .registry import McpRegistryChange, McpRegistrySnapshot, RegistryListener
from .schema import CompiledSchema, SchemaCompiler, SchemaViolation, require_schema_compiler

ContextFactory = Callable[[Mapping[str, Any]], ToolContext]
CompletionHandler = Callable[[ToolContext, Mapping[str, Any], Mapping[str, Any]], object]
_UNSET = object()


class McpServer:
    """Framework-free facade over current stateless MCP server capabilities.

    Registration atomically replaces immutable mapping snapshots.  Invocation
    follows a fixed chain: dialect -> identity -> authorization -> schema ->
    handler -> output schema -> safe wire result.
    """

    def __init__(
        self,
        *,
        identity: Implementation | None = None,
        instructions: str | None = None,
        context_factory: ContextFactory | None = None,
        dialect: McpDialect = DEFAULT_DIALECT,
        schema_compiler: SchemaCompiler | None = None,
        page_size: int = 100,
        invocation_interceptors: tuple[McpInvocationInterceptor, ...] = (),
        audit_sink: McpAuditSink | None = None,
        trace_sink: McpTraceSink | None = None,
        mrtr_state: MrtStateBinding | None = None,
    ) -> None:
        if page_size <= 0 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        self._identity = identity or Implementation("atlas-richie-mcp", "0.1.0")
        self._instructions = instructions
        self._context_factory = context_factory or (lambda _meta: ToolContext())
        self._dialect = dialect
        self._schema_compiler = schema_compiler
        self._page_size = page_size
        self._registry = McpRegistrySnapshot(0, {}, {}, {}, {})
        self._registry_listeners: list[RegistryListener] = []
        self._lock = RLock()
        self._active_cancellations: dict[str | int, CancellationToken] = {}
        self._invocation_pipeline = build_invocation_pipeline(tuple(invocation_interceptors), audit_sink, trace_sink, invoke_handler)
        self._mrtr_state = mrtr_state

    def tool(
        self,
        *,
        name: str | None = None,
        description: str = "",
        title: str | None = None,
        required_scopes: frozenset[str] = frozenset(),
        input_schema: Mapping[str, Any] | None = None,
        output_schema: Mapping[str, Any] | None = None,
        annotations: Mapping[str, Any] | None = None,
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Register immutable tool metadata; the decorator performs no I/O."""

        def register(function: Callable[..., object]) -> Callable[..., object]:
            tool_name = name or function.__name__
            _require_public_name(tool_name, "tool")
            input_compiled = self._compile(input_schema)
            output_compiled = self._compile(output_schema)
            descriptor = ToolDescriptor(
                tool_name, description, function, frozenset(required_scopes), input_schema, output_schema,
                title, dict(annotations or {}), input_compiled, output_compiled,
            )
            with self._lock:
                if tool_name in self._registry.tools:
                    raise ValidationError(f"tool already registered: {tool_name}")
                self._replace_registry(tools={**self._registry.tools, tool_name: descriptor})
            return function

        return register

    def resource(
        self,
        *,
        uri: str,
        name: str,
        description: str | None = None,
        mime_type: str | None = None,
        title: str | None = None,
        required_scopes: frozenset[str] = frozenset(),
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Register a concrete readable resource."""

        def register(function: Callable[..., object]) -> Callable[..., object]:
            _require_public_name(name, "resource")
            if not uri.strip():
                raise ValidationError("resource uri is required")
            descriptor = ResourceDescriptor(uri, name, function, description, mime_type, title, frozenset(required_scopes))
            with self._lock:
                if uri in self._registry.resources:
                    raise ValidationError(f"resource already registered: {uri}")
                self._replace_registry(resources={**self._registry.resources, uri: descriptor})
            return function

        return register

    def resource_template(self, *, uri_template: str, name: str, description: str | None = None, mime_type: str | None = None) -> None:
        """Register discoverable template metadata; resolving it remains an application decision."""

        _require_public_name(name, "resource template")
        if not uri_template.strip():
            raise ValidationError("resource uri template is required")
        descriptor = ResourceTemplateDescriptor(uri_template, name, description, mime_type)
        with self._lock:
            if uri_template in self._registry.resource_templates:
                raise ValidationError(f"resource template already registered: {uri_template}")
            self._replace_registry(resource_templates={**self._registry.resource_templates, uri_template: descriptor})

    def prompt(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        title: str | None = None,
        arguments: tuple[Mapping[str, Any], ...] = (),
        required_scopes: frozenset[str] = frozenset(),
    ) -> Callable[[Callable[..., object]], Callable[..., object]]:
        """Register a prompt renderer returning MCP prompt messages or an InputRequired result."""

        def register(function: Callable[..., object]) -> Callable[..., object]:
            prompt_name = name or function.__name__
            _require_public_name(prompt_name, "prompt")
            descriptor = PromptDescriptor(prompt_name, function, description, title, tuple(arguments), frozenset(required_scopes))
            with self._lock:
                if prompt_name in self._registry.prompts:
                    raise ValidationError(f"prompt already registered: {prompt_name}")
                self._replace_registry(prompts={**self._registry.prompts, prompt_name: descriptor})
            return function

        return register

    def completion(self, function: CompletionHandler) -> CompletionHandler:
        """Set one explicit completion strategy for prompts and resource templates."""

        with self._lock:
            if self._registry.completion_handler is not None:
                raise ValidationError("completion handler already registered")
            self._replace_registry(completion_handler=function)
        return function

    @property
    def registry_snapshot(self) -> McpRegistrySnapshot:
        return self._registry

    def add_registry_listener(self, listener: RegistryListener) -> Callable[[], None]:
        """Observe successful snapshot changes; listener failures never roll back a registry."""
        with self._lock:
            self._registry_listeners.append(listener)
        def remove() -> None:
            with self._lock:
                if listener in self._registry_listeners:
                    self._registry_listeners.remove(listener)
        return remove

    def reload(self, snapshot: McpRegistrySnapshot) -> None:
        """Atomically replace every visible registry mapping with a newer immutable snapshot."""
        with self._lock:
            self._replace_registry(
                tools=snapshot.tools, resources=snapshot.resources,
                resource_templates=snapshot.resource_templates, prompts=snapshot.prompts,
                completion_handler=snapshot.completion_handler,
            )

    async def handle(self, payload: object, *, transport_version: str | None = None, context: ToolContext | None = None) -> dict[str, Any] | None:
        """Handle one JSON value; notifications deliberately never produce a response."""

        request_id: str | int | None = None
        notification = _is_notification(payload)
        try:
            request = self._dialect.parse_request(payload, transport_version=transport_version)
            request_id = request.request_id
            result = await self._dispatch(request, context)
            if not request.is_notification:
                result = {**result, "_meta": {"io.modelcontextprotocol/serverInfo": self._identity.as_json(), **dict(result.get("_meta", {}))}}
            return None if request.is_notification else success(request_id, result, dialect=self._dialect)
        except McpError as error:
            return None if notification else failure(request_id, error)
        except Exception:
            return None if notification else failure(request_id, McpError(-32603, "Internal error"))

    async def _dispatch(self, request: Request, context: ToolContext | None) -> Mapping[str, Any]:
        if request.method == "notifications/cancelled":
            self._cancel(request.params)
            return {"resultType": "complete"}
        if request.method == "server/discover":
            return self._cacheable({
                "supportedVersions": [self._dialect.version],
                "capabilities": self._capabilities(),
                **({"instructions": self._instructions} if self._instructions else {}),
            }, public=True)
        if request.method == "tools/list":
            return self._list(request.params, "tools", self._tools, lambda item: item.public_json())
        if request.method == "tools/call":
            return await self._call_tool(request, context)
        if request.method == "resources/list":
            return self._list(request.params, "resources", self._resources, lambda item: item.public_json())
        if request.method == "resources/templates/list":
            return self._list(request.params, "resourceTemplates", self._resource_templates, lambda item: item.public_json())
        if request.method == "resources/read":
            return await self._read_resource(request, context)
        if request.method == "prompts/list":
            return self._list(request.params, "prompts", self._prompts, lambda item: item.public_json())
        if request.method == "prompts/get":
            return await self._get_prompt(request, context)
        if request.method == "completion/complete":
            return await self._complete(request, context)
        raise ProtocolError(-32601, "Method not found", {"method": request.method})

    async def _call_tool(self, request: Request, context_override: ToolContext | None) -> Mapping[str, Any]:
        name = _required_text(request.params, "name", "tool_name_required")
        arguments = request.params.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "arguments_must_be_object"})
        registry = self._registry
        descriptor = registry.tools.get(name)
        if descriptor is None:
            raise ProtocolError(-32602, "Invalid params", {"reason": "unknown_tool", "name": name})
        context = self._context(request, context_override)
        context = self._with_round_state(request, context, registry.revision)
        self._authorize(context, descriptor.required_scopes)
        self._validate(descriptor.compiled_input_schema, arguments, "input")
        cancellation = context.cancellation
        self._activate_cancellation(request.request_id, cancellation)
        try:
            result = await self._invoke_tool(descriptor, context, arguments)
        finally:
            self._deactivate_cancellation(request.request_id, cancellation)
        if isinstance(result, InputRequired):
            return self._input_required(result, context, registry.revision)
        if isinstance(result, Mapping) and result.get("resultType") == "complete" and result.get("isError") is True:
            return result
        self._validate(descriptor.compiled_output_schema, result, "output")
        return _tool_success(result)

    async def _read_resource(self, request: Request, context_override: ToolContext | None) -> Mapping[str, Any]:
        uri = _required_text(request.params, "uri", "resource_uri_required")
        descriptor = self._resources.get(uri)
        if descriptor is None:
            raise ProtocolError(-32602, "Invalid params", {"reason": "unknown_resource", "uri": uri})
        context = self._context(request, context_override)
        self._authorize(context, descriptor.required_scopes)
        result = await _invoke(descriptor.read, context)
        contents = result if isinstance(result, list | tuple) else [result]
        normalized = [_resource_content(uri, value, descriptor.mime_type) for value in contents]
        return self._cacheable({"contents": normalized}, public=False)

    async def _get_prompt(self, request: Request, context_override: ToolContext | None) -> Mapping[str, Any]:
        name = _required_text(request.params, "name", "prompt_name_required")
        arguments = request.params.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "arguments_must_be_object"})
        registry = self._registry
        descriptor = registry.prompts.get(name)
        if descriptor is None:
            raise ProtocolError(-32602, "Invalid params", {"reason": "unknown_prompt", "name": name})
        context = self._with_round_state(request, self._context(request, context_override), registry.revision)
        self._authorize(context, descriptor.required_scopes)
        rendered = await _invoke(descriptor.render, context, **dict(arguments))
        if isinstance(rendered, InputRequired):
            return self._input_required(rendered, context, registry.revision)
        messages = list(rendered) if isinstance(rendered, tuple | list) else [rendered]
        if not all(isinstance(message, Mapping) for message in messages):
            raise ToolExecutionError(-32603, "Prompt renderer returned invalid messages")
        return {"resultType": "complete", "messages": [dict(message) for message in messages]}

    async def _complete(self, request: Request, context_override: ToolContext | None) -> Mapping[str, Any]:
        handler = self._completion_handler
        if handler is None:
            raise ProtocolError(-32601, "Method not found", {"method": "completion/complete"})
        argument = request.params.get("argument")
        reference = request.params.get("ref")
        if not isinstance(argument, Mapping) or not isinstance(reference, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "completion_argument_and_ref_required"})
        result = await _invoke(handler, self._context(request, context_override), dict(reference), dict(argument))
        if not isinstance(result, CompletionResult):
            raise ToolExecutionError(-32603, "Completion handler must return CompletionResult")
        return {"resultType": "complete", "completion": result.as_json()}

    def _list(self, params: Mapping[str, Any], key: str, source: Mapping[str, Any], mapper: Callable[[Any], dict[str, Any]]) -> Mapping[str, Any]:
        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise ProtocolError(-32602, "Invalid params", {"reason": "cursor_must_be_string"})
        names = tuple(sorted(source))
        start = _cursor_index(cursor, names)
        selected = names[start : start + self._page_size]
        body: dict[str, Any] = {key: [mapper(source[name]) for name in selected]}
        if start + len(selected) < len(names):
            body["nextCursor"] = _cursor_for(names[start + len(selected) - 1])
        return self._cacheable(body, public=False)

    def _capabilities(self) -> dict[str, Any]:
        result: dict[str, Any] = {"tools": {}}
        if self._resources:
            result["resources"] = {"listChanged": False}
        if self._resource_templates:
            result.setdefault("resources", {})["templates"] = True
        if self._prompts:
            result["prompts"] = {"listChanged": False}
        if self._completion_handler:
            result["completions"] = {}
        return result

    def _context(self, request: Request, override: ToolContext | None) -> ToolContext:
        if override is not None:
            return override
        context = self._context_factory(request.meta)
        if not isinstance(context, ToolContext):
            raise McpError(-32603, "Internal error")
        return context

    def _authorize(self, context: ToolContext, required_scopes: frozenset[str]) -> None:
        missing = required_scopes.difference(context.granted_scopes)
        if missing:
            raise ToolExecutionError(-32003, "Insufficient tool scope", {"missingScopes": sorted(missing)})

    def _with_round_state(self, request: Request, context: ToolContext, registry_revision: int) -> ToolContext:
        request_state = request.params.get("requestState")
        input_responses = request.params.get("inputResponses", {})
        if request_state is not None and not isinstance(request_state, str):
            raise ProtocolError(-32602, "Invalid params", {"reason": "request_state_must_be_string"})
        if not isinstance(input_responses, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "input_responses_must_be_object"})
        if any(not isinstance(key, str) or not isinstance(value, Mapping) for key, value in input_responses.items()):
            raise ProtocolError(-32602, "Invalid params", {"reason": "input_responses_must_map_strings_to_objects"})
        continuation_state = request_state
        if request_state is not None and self._mrtr_state is not None:
            try:
                continuation_state = self._mrtr_state.resume(request_state, context, registry_revision=registry_revision)
            except MrtRequestStateError as error:
                raise ProtocolError(-32602, "Invalid params", {"reason": "invalid_request_state"}) from error
        return replace(context, request_state=continuation_state, input_responses=dict(input_responses))

    def _input_required(self, result: InputRequired, context: ToolContext, registry_revision: int) -> Mapping[str, Any]:
        if self._mrtr_state is None:
            return result.as_json()
        signed_state = self._mrtr_state.issue(
            context,
            registry_revision=registry_revision,
            continuation_state=result.request_state,
        )
        return InputRequired(result.input_requests, signed_state).as_json()

    async def _invoke_tool(self, descriptor: ToolDescriptor, context: ToolContext, arguments: Mapping[str, Any]) -> object:
        try:
            return await self._invocation_pipeline(McpInvocation(descriptor, context, dict(arguments)))
        except (ValidationError, ValueError, TypeError, TimeoutError):
            return _tool_error("Tool invocation rejected")
        except (asyncio.CancelledError, McpInvocationCancelled):
            raise
        except Exception:
            return _tool_error("Tool execution failed")

    @property
    def _tools(self) -> Mapping[str, ToolDescriptor]:
        return self._registry.tools

    @property
    def _resources(self) -> Mapping[str, ResourceDescriptor]:
        return self._registry.resources

    @property
    def _resource_templates(self) -> Mapping[str, ResourceTemplateDescriptor]:
        return self._registry.resource_templates

    @property
    def _prompts(self) -> Mapping[str, PromptDescriptor]:
        return self._registry.prompts

    @property
    def _completion_handler(self) -> CompletionHandler | None:
        return self._registry.completion_handler

    def _replace_registry(
        self,
        *,
        tools: Mapping[str, ToolDescriptor] | None = None,
        resources: Mapping[str, ResourceDescriptor] | None = None,
        resource_templates: Mapping[str, ResourceTemplateDescriptor] | None = None,
        prompts: Mapping[str, PromptDescriptor] | None = None,
        completion_handler: CompletionHandler | None | object = _UNSET,
    ) -> None:
        previous = self._registry
        current = McpRegistrySnapshot(
            previous.revision + 1,
            previous.tools if tools is None else tools,
            previous.resources if resources is None else resources,
            previous.resource_templates if resource_templates is None else resource_templates,
            previous.prompts if prompts is None else prompts,
            previous.completion_handler if completion_handler is _UNSET else completion_handler,  # type: ignore[arg-type]
        )
        self._registry = current
        change = McpRegistryChange(previous.revision, current.revision)
        for listener in tuple(self._registry_listeners):
            try:
                listener(change)
            except Exception:
                continue

    def _activate_cancellation(self, request_id: str | int | None, token: CancellationToken) -> None:
        if request_id is None:
            return
        with self._lock:
            self._active_cancellations[request_id] = token

    def _deactivate_cancellation(self, request_id: str | int | None, token: CancellationToken) -> None:
        if request_id is None:
            return
        with self._lock:
            if self._active_cancellations.get(request_id) is token:
                del self._active_cancellations[request_id]

    def _cancel(self, params: Mapping[str, Any]) -> None:
        request_id = params.get("requestId")
        if isinstance(request_id, bool) or not isinstance(request_id, str | int):
            return
        with self._lock:
            token = self._active_cancellations.get(request_id)
        if token is not None:
            token.cancel()

    def _compile(self, schema: Mapping[str, Any] | None) -> CompiledSchema | None:
        if schema is None:
            return None
        return require_schema_compiler(self._schema_compiler).compile(schema)

    @staticmethod
    def _validate(compiled: object | None, value: object, kind: str) -> None:
        if compiled is None:
            return
        violations = compiled.validate(value)  # type: ignore[union-attr]
        if violations:
            raise ProtocolError(-32602, "Invalid params", {"reason": f"{kind}_schema_invalid", "violations": [_violation(item) for item in violations]})

    @staticmethod
    def _cacheable(body: Mapping[str, Any], *, public: bool) -> dict[str, Any]:
        return {"resultType": "complete", "cacheScope": "public" if public else "private", "ttlMs": 0, **body}


async def _invoke(function: Callable[..., object], *args: object, **kwargs: object) -> object:
    try:
        result = function(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    except (ValidationError, ValueError, TypeError) as error:
        return _tool_error(str(error))
    except (asyncio.CancelledError, McpInvocationCancelled):
        raise
    except Exception:
        return _tool_error("Tool execution failed")


def _tool_success(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return {"resultType": "complete", "content": [], "structuredContent": dict(value)}
    return {"resultType": "complete", "content": [{"type": "text", "text": str(value)}]}


def _tool_error(message: str) -> Mapping[str, Any]:
    return {"resultType": "complete", "isError": True, "content": [{"type": "text", "text": message}]}


def _resource_content(uri: str, value: object, mime_type: str | None) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    result: dict[str, Any] = {"uri": uri, "text": str(value)}
    if mime_type:
        result["mimeType"] = mime_type
    return result


def _required_text(params: Mapping[str, Any], key: str, reason: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ProtocolError(-32602, "Invalid params", {"reason": reason})
    return value


def _require_public_name(value: str, noun: str) -> None:
    if not value or value.startswith("_"):
        raise ValidationError(f"{noun} name must be public and non-empty")


def _cursor_for(name: str) -> str:
    return base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_index(cursor: str | None, names: tuple[str, ...]) -> int:
    if cursor is None:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        marker = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        return names.index(marker) + 1
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError(-32602, "Invalid params", {"reason": "invalid_cursor"}) from None


def _violation(value: SchemaViolation) -> dict[str, str]:
    return {"instancePath": value.instance_path, "schemaPath": value.schema_path, "message": value.message}


def _is_notification(payload: object) -> bool:
    return isinstance(payload, Mapping) and "id" not in payload
