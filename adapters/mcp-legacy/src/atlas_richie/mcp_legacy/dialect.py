"""Legacy session-era MCP request and result normalization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atlas_richie.mcp import Implementation, McpError, ProtocolError
from atlas_richie.mcp.protocol import JSON_RPC_VERSION, Request

LEGACY_PROTOCOL_VERSION = "2025-11-25"
_INITIALIZE_METHOD = "initialize"
_DISCOVER_METHOD = "server/discover"
_COMPLETE_RESULT_TYPE = "complete"


@dataclass(frozen=True, slots=True)
class LegacyMcpServerDialect:
    """Maps legacy initialize metadata onto the modern server discovery operation."""

    version: str = LEGACY_PROTOCOL_VERSION

    def parse_request(self, payload: object, *, transport_version: str | None = None) -> Request:
        if not isinstance(payload, Mapping):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "object_required"})
        if payload.get("jsonrpc") != JSON_RPC_VERSION:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "jsonrpc_must_be_2.0"})
        method = payload.get("method")
        if not isinstance(method, str) or not method:
            raise ProtocolError(-32600, "Invalid Request", {"reason": "method_required"})
        notification = "id" not in payload
        request_id = payload.get("id")
        if not notification and (request_id is None or isinstance(request_id, bool) or not isinstance(request_id, str | int)):
            raise ProtocolError(-32600, "Invalid Request", {"reason": "id_must_be_string_or_integer"})
        params = payload.get("params", {})
        if not isinstance(params, Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "params_must_be_object"})
        if method.startswith("notifications/"):
            return Request(request_id, method, params, {}, is_notification=True)
        if method == _INITIALIZE_METHOD:
            self._validate_initialize(params)
            return Request(request_id, _DISCOVER_METHOD, {}, {}, is_notification=notification)
        if transport_version is not None and transport_version != self.version:
            raise _unsupported_version(transport_version, self.version)
        return Request(request_id, method, params, {}, is_notification=notification)

    def encode_result(self, result: Mapping[str, Any]) -> dict[str, Any]:
        result_type = result.get("resultType")
        if result_type != _COMPLETE_RESULT_TYPE:
            raise ProtocolError(-32602, "Invalid params", {"reason": "legacy_result_type_unsupported"})
        encoded = dict(result)
        del encoded["resultType"]
        return encoded

    def _validate_initialize(self, params: Mapping[str, Any]) -> None:
        if params.get("protocolVersion") != self.version:
            raise _unsupported_version(params.get("protocolVersion"), self.version)
        if not isinstance(params.get("clientInfo"), Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "legacy_client_info_required"})
        if not isinstance(params.get("capabilities"), Mapping):
            raise ProtocolError(-32602, "Invalid params", {"reason": "legacy_capabilities_required"})


@dataclass(frozen=True, slots=True)
class LegacyMcpClientDialect:
    """Maps modern client facade calls onto legacy initialize and implicit complete results."""

    version: str = LEGACY_PROTOCOL_VERSION

    def encode_request(
        self,
        *,
        request_id: int,
        method: str,
        params: Mapping[str, Any],
        identity: Implementation,
        capabilities: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if method == _DISCOVER_METHOD:
            return {
                "jsonrpc": JSON_RPC_VERSION,
                "id": request_id,
                "method": _INITIALIZE_METHOD,
                "params": {
                    "protocolVersion": self.version,
                    "clientInfo": identity.as_json(),
                    "capabilities": dict(capabilities),
                },
            }
        return {"jsonrpc": JSON_RPC_VERSION, "id": request_id, "method": method, "params": dict(params)}

    def decode_result(self, response: Mapping[str, Any]) -> Mapping[str, Any]:
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise McpError(-32603, "Invalid legacy result response")
        if result.get("resultType") not in {None, _COMPLETE_RESULT_TYPE}:
            raise McpError(-32603, "Legacy endpoint returned an unsupported result type")
        return {"resultType": _COMPLETE_RESULT_TYPE, **dict(result)}


def _unsupported_version(actual: object, expected: str) -> ProtocolError:
    return ProtocolError(-32022, "Unsupported protocol version", {"supported": [expected], "requested": actual})
