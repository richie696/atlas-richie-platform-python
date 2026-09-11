"""MCP 失败，独立于传输与框架表达。

中文
----
`McpError` 是 `PlatformError` 的 dataclass 子类，携带：

- `code`：JSON-RPC 兼容的整数错误码（业务可分类）。
- `message`：面向开发者 / LLM 的可读消息。
- `data`：可选的诊断负载（必须是 `Mapping`）。

子类型：

- `ProtocolError`：当前选定的 MCP dialect 无法解析 / 编码请求。
- `ToolExecutionError`：注册的 tool 在合法调用上拒绝或失败。
- `AuthenticationError`：adapter 无法为本次请求建立安全 principal。

选择不绑定任何具体传输 / 框架（Spring Boot / FastAPI / aiohttp 等），
业务侧只需 `except McpError` 即可统一捕获所有 MCP 相关失败。

English
--------
MCP failures represented independently from a transport or framework.

`McpError` is a frozen dataclass subclass of `PlatformError` carrying:

- `code`: a JSON-RPC-compatible integer error code (machine-readable).
- `message`: a developer / LLM-facing message.
- `data`: optional diagnostic payload (must be a `Mapping`).

Subtypes:

- `ProtocolError`: a request cannot be parsed or encoded under the
  selected MCP dialect.
- `ToolExecutionError`: a registered tool rejected or failed while
  processing a valid invocation.
- `AuthenticationError`: an adapter could not establish a safe
  principal for this request.

Deliberately transport- / framework-neutral: business code only needs
`except McpError` to catch every MCP-side failure regardless of whether
the transport is Spring Boot, FastAPI, aiohttp, …

Mirrors `cn.richie696.component.mcp.api.McpException` (Java — different
shape, same role as the root MCP failure class).
"""

from dataclasses import dataclass
from typing import Any, Mapping

from atlas_richie.contracts import PlatformError


@dataclass(frozen=True, slots=True)
class McpError(PlatformError):
    """中文
    ----
    JSON-RPC 兼容的 MCP 错误，携带稳定诊断 `data`。

    English
    --------
    A JSON-RPC-compatible MCP error with stable diagnostic data.
    """

    code: int
    message: str
    data: Mapping[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        """中文
        ----
        渲染为 JSON-RPC 错误对象的 `code` / `message` / `data` 形态（`data`
        防御性拷贝避免外部突变）。

        Returns:
            包含 `code`、`message`，以及可选 `data` 拷贝的 dict。

        English
        --------
        Render to the JSON-RPC error object shape
        (`code` / `message` / `data`); `data` is defensively copied to
        isolate the wire payload from the caller's mapping.

        Returns:
            A dict containing `code`, `message`, and a defensive copy of
            `data` if present.
        """
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = dict(self.data)
        return result


class ProtocolError(McpError):
    """中文
    ----
    在当前选定的 MCP dialect 下请求无法被解析 / 编码。

    English
    --------
    A request cannot be interpreted under the selected MCP dialect.
    """


class ToolExecutionError(McpError):
    """中文
    ----
    已注册的 tool 在合法的调用上拒绝或失败。

    English
    --------
    A registered tool rejected or failed while processing a valid
    invocation.
    """


class AuthenticationError(McpError):
    """中文
    ----
    适配器无法为本次请求建立安全 principal。

    English
    --------
    An adapter could not establish a safe principal for this request.
    """
