"""MCP failures represented independently from a transport or framework."""

from dataclasses import dataclass
from typing import Any, Mapping

from atlas_richie.contracts import PlatformError


@dataclass(frozen=True, slots=True)
class McpError(PlatformError):
    """A JSON-RPC-compatible MCP error with stable diagnostic data."""

    code: int
    message: str
    data: Mapping[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            result["data"] = dict(self.data)
        return result


class ProtocolError(McpError):
    """A request cannot be interpreted under the selected MCP dialect."""


class ToolExecutionError(McpError):
    """A registered tool rejected or failed while processing a valid invocation."""


class AuthenticationError(McpError):
    """An adapter could not establish a safe principal for this request."""
