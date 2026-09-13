"""Atlas Richie Cluster Token Protocol V1 — deny_reason 枚举 (frozen).

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §4.2. V1 frozen,
4 个允许值. 任何新增走 V1.1 minor + ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ClusterDenyReason(StrEnum):
    """Cluster Token Protocol V1 — 4 deny_reason (frozen, ACQUIRE/RENEW RESPONSE)."""

    QUEUE_FULL = "QUEUE_FULL"
    RATE_LIMITED = "RATE_LIMITED"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STALE_EPOCH = "STALE_EPOCH"
    UNKNOWN = "UNKNOWN"


__all__ = ["ClusterDenyReason"]
