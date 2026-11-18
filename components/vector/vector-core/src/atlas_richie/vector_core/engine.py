"""provider 适配器需要实现的向量 Store 协议。

对应 Java `VectorAdvancedSearchOperations` / `VectorStoreCapabilities` 的
组合，但收敛成一个最小协议：能力声明、分数语义、写入、向量检索、删除。
文本/混合检索、索引生命周期等按 provider 能力可选扩展，不塞进核心协议，
避免不支持的 provider 被迫写一堆抛 UnsupportedOperationException 的桩。
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .model import VectorRecord, VectorSearchResult
from .query import ResolvedVectorQuery
from .topology import VectorScoreSemantics, VectorStoreCapabilities, VectorStoreId


@runtime_checkable
class VectorStoreEngine(Protocol):
    @property
    def store_id(self) -> VectorStoreId: ...

    def capabilities(self) -> VectorStoreCapabilities: ...

    def score_semantics(self) -> VectorScoreSemantics: ...

    def upsert(self, records: Sequence[VectorRecord]) -> int: ...

    def search(
        self, query_vector: Sequence[float], resolved: ResolvedVectorQuery
    ) -> list[VectorSearchResult]: ...

    def delete(self, ids: Sequence[str]) -> int: ...

    def close(self) -> None: ...


class VectorStoreError(RuntimeError):
    """provider 侧访问失败。"""


class VectorStoreNotExistsError(VectorStoreError):
    """目标索引/表不存在。"""


class VectorStoreAccessDeniedError(VectorStoreError):
    """凭证无权访问目标索引/表。"""


class VectorProviderUnavailableError(VectorStoreError):
    """provider 不可达。"""


class VectorCapabilityMismatchError(VectorStoreError):
    """请求的操作超出 Store 声明的能力。"""


__all__ = [
    "VectorStoreEngine",
    "VectorStoreError",
    "VectorStoreNotExistsError",
    "VectorStoreAccessDeniedError",
    "VectorProviderUnavailableError",
    "VectorCapabilityMismatchError",
]