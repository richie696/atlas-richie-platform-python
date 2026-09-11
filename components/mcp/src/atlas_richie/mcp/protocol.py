"""Versioned, stateless MCP 2026-07-28 wire protocol primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import McpError, ProtocolError

JSON_RPC_VERSION = "2.0"
MODERN_PROTOCOL_VERSION = "2026-07-28"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"


@dataclass(frozen=True, slots=True)
class Implementation:
    """The stable, serializable identity advertised by an MCP endpoint."""

    name: str
    version: str
    title: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise ValueError("implementation name and version are required")

    def as_json(self) -> dict[str, str]:
        result = {"name": self.name, "version": self.version}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class Request:
    """A normalized MCP request; business code never receives the raw envelope."""

    request_id: str | int | None
    method: str
    params: Mapping[str, Any]
    meta: Mapping[str, Any]
    is_notification: bool = False


class McpDialect(Protocol):
    """Strategy boundary for future MCP protocol generations."""

    @property
    def version(self) -> str: ...

    def parse_request(self, payload: object, *, transport_version: str | None = None) -> Request: ...

    def encode_result(self, result: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class Mcp20260728Dialect:
    """The stateless dialect: request metadata replaces initialize/session state."""

    version: str = MODERN_PROTOCOL_VERSION

    def parse_request(self, payload: object, *, transport_version: str | None = None) -> Request:
        if not isinstance(payload, Mapping):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "object_required"})
        if payload.get("jsonrpc") != JSON_RPC_VERSION:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "jsonrpc_must_be_2.0"})
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "method_required"})
        is_notification = "id" not in payload
        raw_id = payload.get("id")
        if not is_notification and (raw_id is None or isinstance(raw_id, bool) or not isinstance(raw_id, str | int)):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "id_must_be_string_or_integer"})
        params = payload.get("params", {})
        if not isinstance(params, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "params_must_be_object"})
        if method.startswith("notifications/"):
            return Request(raw_id, method, params, {}, is_notification=True)
        meta = params.get("_meta")
        if not isinstance(meta, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "modern_meta_required"})
        request_version = meta.get(PROTOCOL_VERSION_META_KEY)
        if request_version != self.version:
            raise ProtocolError(-32022, "Unsupported protocol version", {"supported": [self.version], "requested": request_version})
        if transport_version is not None and request_version != transport_version:
            raise ProtocolError(-32020, "MCP-Protocol-Version header does not match request metadata", {"metadata": request_version, "header": transport_version})
        if not isinstance(meta.get(CLIENT_CAPABILITIES_META_KEY), Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "client_capabilities_required"})
        client_info = meta.get(CLIENT_INFO_META_KEY)
        if client_info is not None and not isinstance(client_info, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "client_info_must_be_object"})
        return Request(raw_id, method, params, meta, is_notification=is_notification)

    def encode_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        encoded = dict(result)
        if encoded.get("resultType") not in {"complete", "input_required"}:
            raise ProtocolError(-32603, "Internal error", {"reason": "result_type_required"})
        return encoded


DEFAULT_DIALECT = Mcp20260728Dialect()


def parse_request(payload: object, *, transport_version: str | None = None) -> Request:
    """Compatibility facade for the default current dialect."""

    return DEFAULT_DIALECT.parse_request(payload, transport_version=transport_version)


def success(request_id: str | int, result: Mapping[str, Any], *, dialect: McpDialect = DEFAULT_DIALECT) -> dict[str, Any]:
    """Create a JSON-RPC success envelope after dialect-level result validation."""

    return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "result": dialect.encode_result(result)}


def failure(request_id: str | int | None, error: McpError) -> dict[str, Any]:
    """Create a JSON-RPC error envelope without exposing implementation details."""

    return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "error": error.as_json()}
