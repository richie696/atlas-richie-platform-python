"""Stable framework-neutral contracts for Atlas Richie components.

包含:
- 基础 lifecycle 协议 (``AsyncCloseable``)
- 错误基类 (``PlatformError`` / ``CapabilityUnavailable`` / ``ValidationError``)
- 能力描述符 (``CapabilityDescriptor``)
- 跨语言 wire protocol V1 Python 投影:
  * ``atlas_richie.contracts.cluster.v1`` (M6.3.1 V1 frozen, 1:1 镜像
    ``docs/protocols/CLUSTER_TOKEN_PROTOCOL.md``)
  * ``atlas_richie.contracts.reporting.v1`` (M6.5.7 V1 frozen, 1:1 镜像
    ``docs/protocols/AGENT_REPORTING_PROTOCOL.md``)

V1 frozen 协议: 任何变更走 V1.1 minor + ADR; V2 major 破坏兼容, 独立 ADR.
"""

from .capability import CapabilityDescriptor
from .errors import CapabilityUnavailable, PlatformError, ValidationError
from .lifecycle import AsyncCloseable

__all__ = [
    "AsyncCloseable",
    "CapabilityDescriptor",
    "CapabilityUnavailable",
    "PlatformError",
    "ValidationError",
]
