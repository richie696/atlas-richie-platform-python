"""Atlas Richie Cluster Token Protocol V1 — message_kind 枚举 (frozen).

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §2. V1 frozen,
6 个允许值. 任何新增走 V1.1 minor + ADR.
"""

from __future__ import annotations

from enum import StrEnum


class ClusterMessageKind(StrEnum):
    """Cluster Token Protocol V1 — 6 message_kind (frozen).

    协议: ``atlas-richie.cluster.token/v1``.
    配套设计文档: ``docs/M6.3-CLUSTER-TOKEN-DESIGN.md``.
    """

    ACQUIRE_REQUEST = "ACQUIRE_REQUEST"
    ACQUIRE_RESPONSE = "ACQUIRE_RESPONSE"
    RELEASE_REQUEST = "RELEASE_REQUEST"
    RENEW_REQUEST = "RENEW_REQUEST"
    RENEW_RESPONSE = "RENEW_RESPONSE"
    ERROR_RESPONSE = "ERROR_RESPONSE"


__all__ = ["ClusterMessageKind"]
