"""向量投影持久化层的运行参数。

对应 Java `VectorProjectionDaoProperties`（`platform.component.vector.projection.*`）。
Java 侧由 Spring `@ConfigurationProperties` 注入，此处改为显式构造——Python 侧不引入
配置框架，参数由调用方在构造 store 时传入。

两个参数的取值都有业务后果：
- `cleanup_delay`：新版本 ACTIVE 之后，旧版本进入 RETIRING 的宽限期。太短会在读链路
  仍使用旧版本时把它删掉；太长会让向量库残留更多向量。
- `delete_batch_size`：清理时单批下发给 provider 的 vectorId 数量，受 provider 单次请求
  上限约束；超过上限可能导致部分删除失败并需要重试。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

DEFAULT_CLEANUP_DELAY = timedelta(hours=24)
DEFAULT_DELETE_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class VectorProjectionProperties:
    """投影 DAO 的两个核心参数。"""

    cleanup_delay: timedelta = DEFAULT_CLEANUP_DELAY
    delete_batch_size: int = DEFAULT_DELETE_BATCH_SIZE

    def __post_init__(self) -> None:
        if self.cleanup_delay is None or self.cleanup_delay < timedelta(0):
            raise ValueError("cleanup_delay must not be negative")
        if self.delete_batch_size <= 0:
            raise ValueError("delete_batch_size must be positive")


__all__ = [
    "VectorProjectionProperties",
    "DEFAULT_CLEANUP_DELAY",
    "DEFAULT_DELETE_BATCH_SIZE",
]
