"""Atlas Richie Cluster Token Protocol V1 — error_code 枚举 (frozen).

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §6. V1 frozen,
9 个允许值. 任何新增走 V1.1 minor + ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ClusterErrorCode(StrEnum):
    """Cluster Token Protocol V1 — 9 error_code (frozen)."""

    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    MALFORMED_ENVELOPE = "MALFORMED_ENVELOPE"
    UNKNOWN_MESSAGE_KIND = "UNKNOWN_MESSAGE_KIND"
    STALE_EPOCH = "STALE_EPOCH"
    LEASE_NOT_FOUND = "LEASE_NOT_FOUND"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    RESOURCE_NOT_CONFIGURED = "RESOURCE_NOT_CONFIGURED"
    SERVER_OVERLOADED = "SERVER_OVERLOADED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


__all__ = ["ClusterErrorCode"]
