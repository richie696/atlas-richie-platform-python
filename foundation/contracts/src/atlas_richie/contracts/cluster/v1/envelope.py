"""Atlas Richie Cluster Token Protocol V1 — envelope frozen dataclass.

1:1 镜像 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §3. 所有消息共享同一
envelope 形状, 仅 ``payload`` 是 per-kind frozen object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .message_kind import ClusterMessageKind


@dataclass(frozen=True, slots=True)
class ClusterTokenEnvelope:
    """Cluster Token Protocol V1 — envelope (8 必填 + payload).

    字段定义见 ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md`` §3.2.
    """

    protocol_version: str
    message_kind: ClusterMessageKind
    request_id: str
    instance_id: str
    startup_epoch: int
    resource: str
    permits: float
    deadline_ns: int
    client_requested_at: str  # ISO 8601 UTC microsecond
    server_received_at: str  # ISO 8601 UTC microsecond (Server 写)
    payload: dict[str, Any]


__all__ = ["ClusterTokenEnvelope"]
