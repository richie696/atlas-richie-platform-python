"""MCP 2026-07-28 框架无关核心 + 传输、安全与 Schema 实现。

中文
----
`atlas-richie-mcp` 组件的 Python 公共 API 入口。

**单 wheel + 子包**结构，对位 Java `atlas-richie-mcp-parent` 的 10 个
子模块（`mcp-api` / `mcp-protocol` / `mcp-server-core` / `mcp-transport-http`
/ `mcp-transport-stdio` / `mcp-security-oauth` / `mcp-schema` /
`mcp-testkit` / Spring Boot starters），但合并到一个 `atlas-richie-mcp`
wheel 内，按目录区分子能力（无 pluggable backend 多实现需求，单包更轻）。

子能力（子包路径）：

- `atlas_richie.mcp.transport.stdio` — stdio newline framing（Java `mcp-transport-stdio`）
- `atlas_richie.mcp.transport.http` — client 出站 Streamable HTTP + SSE 消费
  （Java `mcp-transport-http` + client starter 的纯 transport 部分）
- `atlas_richie.mcp.transport.asgi` — server-side ASGI 桥（Python 独有）
- `atlas_richie.mcp.security.oauth` — OAuth Bearer → ToolContext + M2M 资源指示
  （Java `mcp-security-oauth`）
- `atlas_richie.mcp.schema.port` — JSON Schema 编译端口（Java `mcp-schema` 端口）
- `atlas_richie.mcp.schema.jsonschema` — Draft 2020-12 实现（对接 `jsonschema` 三方库）
- `atlas_richie.mcp.legacy` — 2025-11-25 旧版协议兼容 dialect
- `atlas_richie.mcp.testkit` — 协议夹具（Java `mcp-testkit`，Python 端预留）

包含：

- **协议与契约**：`McpClient` / `McpServer` / `McpDialect` / `Mcp20260728Dialect`
  / `Implementation` / `Request` / `parse_request` / `success` / `failure`
- **工具 / 资源 / 提示词**：`ToolDescriptor` / `ResourceDescriptor` /
  `ResourceTemplateDescriptor` / `PromptDescriptor` / `CompletionResult`
  / `InputRequired` / `ProgressReporter` / `ProgressUpdate`
- **上下文与取消**：`ToolContext` / `CancellationToken` / `McpInvocationCancelled`
- **注册表**：`McpRegistrySnapshot` / `McpRegistryChange` / `RegistryListener`
- **调用链**：`McpInvocation` / `McpInvocationInterceptor` /
  `McpAuditEvent` / `McpAuditSink` / `McpTraceEvent` / `McpTraceSink`
- **MRTR 多轮请求状态**：`MrtRequestState` / `MrtRequestStateCodec` /
  `MrtRequestStateError` / `MrtStateBinding` / `PrincipalFingerprint`
- **错误模型**：`McpError` / `ProtocolError` / `ToolExecutionError` /
  `AuthenticationError`
- **传输相关**：`McpResponseCache`

English
--------
Framework-neutral MCP 2026-07-28 core plus transport, security, and
schema implementations — the public Python entry point for the
`atlas-richie-mcp` component.

**Single wheel + sub-packages** layout, mirroring the 10 sub-modules
of the Java `atlas-richie-mcp-parent` (`mcp-api` / `mcp-protocol` /
`mcp-server-core` / `mcp-transport-http` / `mcp-transport-stdio` /
`mcp-security-oauth` / `mcp-schema` / `mcp-testkit` / Spring Boot
starters). No pluggable backend polymorphism → one wheel is enough;
sub-capabilities are separated by directory.

Sub-capabilities (sub-package paths):

- `atlas_richie.mcp.transport.stdio` — stdio newline framing
  (Java `mcp-transport-stdio`).
- `atlas_richie.mcp.transport.http` — outbound client Streamable
  HTTP + SSE consumer (Java `mcp-transport-http` + client starter's
  transport-only slice).
- `atlas_richie.mcp.transport.asgi` — server-side ASGI bridge
  (Python-only, no Java equivalent).
- `atlas_richie.mcp.security.oauth` — OAuth Bearer → ToolContext +
  M2M resource indicator (Java `mcp-security-oauth`).
- `atlas_richie.mcp.schema.port` — JSON Schema compiler port
  (Java `mcp-schema` port).
- `atlas_richie.mcp.schema.jsonschema` — Draft 2020-12
  implementation (binds the `jsonschema` third-party library).
- `atlas_richie.mcp.legacy` — 2025-11-25 legacy wire dialect.
- `atlas_richie.mcp.testkit` — protocol fixtures
  (Java `mcp-testkit`; reserved for Python use).

Exports (grouped by concern):

- **Protocol + contracts**: `McpClient`, `McpServer`, `McpDialect`,
  `Mcp20260728Dialect`, `Implementation`, `Request`, `parse_request`,
  `success`, `failure`.
- **Tool / resource / prompt**: `ToolDescriptor`, `ResourceDescriptor`,
  `ResourceTemplateDescriptor`, `PromptDescriptor`, `CompletionResult`,
  `InputRequired`, `ProgressReporter`, `ProgressUpdate`.
- **Context + cancellation**: `ToolContext`, `CancellationToken`,
  `McpInvocationCancelled`.
- **Registry**: `McpRegistrySnapshot`, `McpRegistryChange`,
  `RegistryListener`.
- **Invocation chain**: `McpInvocation`, `McpInvocationInterceptor`,
  `McpAuditEvent`, `McpAuditSink`, `McpTraceEvent`, `McpTraceSink`.
- **MRTR (multi-round request state)**: `MrtRequestState`,
  `MrtRequestStateCodec`, `MrtRequestStateError`, `MrtStateBinding`,
  `PrincipalFingerprint`.
- **Error model**: `McpError`, `ProtocolError`, `ToolExecutionError`,
  `AuthenticationError`.
- **Transport-side**: `McpResponseCache`.

Mirrors the `atlas-richie-mcp-parent` Java multi-module set under
`cn.richie696.component.mcp.*`, but is a fresh framework-neutral
implementation (no Spring Boot dependency, single wheel).
"""

from .client import McpClient
from .cache import McpResponseCache
from .cancellation import CancellationToken, McpInvocationCancelled
from .errors import AuthenticationError, McpError, ProtocolError, ToolExecutionError
from .models import CompletionResult, InputRequired, ProgressReporter, ProgressUpdate, ResourceDescriptor, ResourceTemplateDescriptor, ToolContext
from .mrtr import MrtRequestState, MrtRequestStateCodec, MrtRequestStateError, MrtStateBinding, PrincipalFingerprint
from .registry import McpRegistryChange, McpRegistrySnapshot
from .invocation import McpAuditEvent, McpAuditSink, McpInvocation, McpInvocationInterceptor, McpTraceEvent, McpTraceSink
from .protocol import Implementation, Mcp20260728Dialect
from .server import McpServer

__all__ = [
    "McpClient",
    "McpResponseCache",
    "CancellationToken",
    "Mcp20260728Dialect",
    "McpError",
    "McpInvocationCancelled",
    "McpInvocation",
    "McpInvocationInterceptor",
    "McpAuditEvent",
    "McpAuditSink",
    "McpTraceEvent",
    "McpTraceSink",
    "McpRegistryChange",
    "McpRegistrySnapshot",
    "MrtRequestState",
    "MrtRequestStateCodec",
    "MrtRequestStateError",
    "MrtStateBinding",
    "PrincipalFingerprint",
    "AuthenticationError",
    "McpServer",
    "Implementation",
    "InputRequired",
    "ProtocolError",
    "ProgressReporter",
    "ProgressUpdate",
    "CompletionResult",
    "ResourceDescriptor",
    "ResourceTemplateDescriptor",
    "ToolContext",
    "ToolExecutionError",
]
