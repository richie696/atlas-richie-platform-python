"""MCP 2026-07-28 框架无关核心 + stdio 传输。

中文
----
`atlas-richie-mcp` 组件的 Python 公共 API 入口：协议门面、注册表、调用链、
MRTR 状态、错误模型、stdio 传输。

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
Framework-neutral MCP 2026-07-28 core and stdio transport — the public
Python entry point for the `atlas-richie-mcp` component.

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
implementation (no Spring Boot dependency).
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
