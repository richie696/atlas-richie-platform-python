"""Stable framework-neutral contracts for Atlas Richie components.

包含:
- 基础 lifecycle 协议 (``AsyncCloseable``)
- 错误基类 (``PlatformError`` / ``CapabilityUnavailable`` / ``ValidationError``)
- 能力描述符 (``CapabilityDescriptor``)
- 跨语言 wire protocol Python 投影:
  * ``atlas_richie.contracts.cluster.v1`` (M6.3.1 V1 frozen, 1:1 镜像
    ``docs/protocol/cluster-token-protocol-v1.md``)
  * ``atlas_richie.contracts.reporting.v1`` (M6.5.7 V1 DRAFT, 1:1 镜像
    ``docs/protocol/上报协议-01-envelope-v1.md`` + ``-02-transport-v1.md`` +
    ``-03-freeze-v1.md``)

V1 frozen 协议: 任何变更走 V1.x spec revision (加 optional field) 或
V2 major + 独立 ADR (改语义 / 改枚举 / 改 wire string). 跨语言合同测试
(Go / Java SDK mock) 走 M6.5.7 sign-off 后 worker 跑.
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
